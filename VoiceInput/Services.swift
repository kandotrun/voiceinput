import AppKit
import AVFoundation
import Security

struct VoiceError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

enum TokenStore {
    static let service = "com.kan.voiceinput"
    static func override() -> String {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "token",
            kSecReturnData as String: true]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
    static func save(_ token: String) throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "token"]
        if token.isEmpty { SecItemDelete(query as CFDictionary); return }
        let data = Data(token.utf8)
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = query; item[kSecValueData as String] = data
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else {
                throw VoiceError(message: "キーチェーンに保存できませんでした。")
            }
        } else if status != errSecSuccess { throw VoiceError(message: "キーチェーンを更新できませんでした。") }
    }
    static func resolve() throws -> String {
        let saved = override()
        if !saved.isEmpty { return saved }
        let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("transcribe-endpoint/.env")
        guard let content = try? String(contentsOf: url, encoding: .utf8) else {
            throw VoiceError(message: "トークンを読み取れません。設定で指定してください。")
        }
        for line in content.components(separatedBy: .newlines) {
            var line = line.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("export ") { line.removeFirst(7) }
            guard let equal = line.firstIndex(of: "="), line[..<equal].trimmingCharacters(in: .whitespaces) == "TRANSCRIBE_TOKEN" else { continue }
            var value = String(line[line.index(after: equal)...]).trimmingCharacters(in: .whitespaces)
            if value.hasPrefix("\"") || value.hasPrefix("'") {
                let quote = value.removeFirst()
                if let end = value.firstIndex(of: quote) { value = String(value[..<end]) }
            } else if let comment = value.range(of: " #") { value = String(value[..<comment.lowerBound]) }
            if !value.isEmpty { return value }
        }
        throw VoiceError(message: "TRANSCRIBE_TOKEN が未設定です。")
    }
}

final class Recorder {
    private let engine = AVAudioEngine()
    private var output: AVAudioFile?
    private var converter: AVAudioConverter?
    private var failure = false
    private var frames: Int64 = 0
    private var energy: Double = 0
    private var url: URL?
    private let lock = NSLock()
    private var tapped = false
    static var recordings: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("voiceinput/再試行用音声", isDirectory: true)
    }
    func start() throws {
        let fm = FileManager.default
        try fm.createDirectory(at: Self.recordings, withIntermediateDirectories: true,
                               attributes: [.posixPermissions: 0o700])
        let url = Self.recordings.appendingPathComponent("録音-\(UUID().uuidString).wav")
        let input = engine.inputNode
        let source = input.outputFormat(forBus: 0)
        guard source.sampleRate > 0, source.channelCount > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: source, to: target) else {
            throw VoiceError(message: "マイクの音声形式を取得できません。")
        }
        self.url = url; self.converter = converter
        output = try AVAudioFile(forWriting: url, settings: target.settings)
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        frames = 0; energy = 0; failure = false
        input.installTap(onBus: 0, bufferSize: 2048, format: source) { [weak self] buffer, _ in
            guard let self else { return }
            self.lock.lock(); defer { self.lock.unlock() }
            let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * 16000 / source.sampleRate)) + 32
            guard let converted = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { self.failure = true; return }
            var supplied = false
            var error: NSError?
            let status = converter.convert(to: converted, error: &error) { _, state in
                if supplied { state.pointee = .noDataNow; return nil }
                supplied = true; state.pointee = .haveData; return buffer
            }
            guard status != .error, error == nil else { self.failure = true; return }
            if let samples = converted.floatChannelData?[0] {
                for i in 0..<Int(converted.frameLength) { self.energy += Double(samples[i] * samples[i]) }
            }
            self.frames += Int64(converted.frameLength)
            do { try self.output?.write(from: converted) } catch { self.failure = true }
        }
        tapped = true
        do { engine.prepare(); try engine.start() } catch { _ = finish(discard: true); throw error }
    }
    struct Result { let url: URL; let valid: Bool; let failed: Bool }
    func finish(discard: Bool = false) -> Result? {
        engine.stop()
        if tapped { engine.inputNode.removeTap(onBus: 0); tapped = false }
        lock.lock(); defer { lock.unlock() }
        output = nil; converter = nil
        guard let url else { return nil }
        self.url = nil
        let rms = frames > 0 ? sqrt(energy / Double(frames)) : 0
        let valid = Double(frames) / 16000 >= 0.3 && rms >= 0.003
        if discard || (!valid && !failure) { try? FileManager.default.removeItem(at: url) }
        return Result(url: url, valid: valid, failed: failure)
    }
}

struct Transcriber {
    static func transcribe(file: URL, endpoint: String, correct: Bool, tokenProvider: () throws -> String = TokenStore.resolve) async throws -> String {
        guard var components = URLComponents(string: endpoint),
              ["http", "https"].contains(components.scheme?.lowercased() ?? ""),
              components.host != nil, components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil else {
            throw VoiceError(message: "エンドポイントURLが正しくありません。")
        }
        components.path = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = components.path.isEmpty ? "/transcribe" : "/\(components.path)/transcribe"
        guard let url = components.url else { throw VoiceError(message: "URLを作成できません。") }
        let boundary = "voiceinput-\(UUID().uuidString)"
        var body = Data()
        func append(_ s: String) { body.append(Data(s.utf8)) }
        for (name, value) in [("language", "ja"), ("correct", correct ? "true" : "false")] {
            append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n")
        }
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"\r\nContent-Type: audio/wav\r\n\r\n")
        body.append(try Data(contentsOf: file)); append("\r\n--\(boundary)--\r\n")
        var request = URLRequest(url: url); request.httpMethod = "POST"; request.timeoutInterval = 180
        request.setValue("Bearer \(try tokenProvider())", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        // Do not forward a bearer token to another host through redirects.
        let session = URLSession(configuration: .ephemeral, delegate: NoRedirect(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw VoiceError(message: "文字起こしサーバーが失敗を返しました（HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)）。")
        }
        struct Response: Decodable { let text: String }
        guard let result = try? JSONDecoder().decode(Response.self, from: data) else {
            throw VoiceError(message: "文字起こし結果の形式が正しくありません。")
        }
        guard !result.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw VoiceError(message: "文字起こし結果が空でした。音声を保持しました。")
        }
        return result.text
    }
    private final class NoRedirect: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
    }
}

@MainActor
enum Paster {
    static func insert(_ text: String, target: NSRunningApplication, restore: Bool) async throws {
        guard AXIsProcessTrusted(), !target.isTerminated else { throw VoiceError(message: "挿入先またはアクセシビリティ権限を確認してください。") }
        for _ in 0..<100 {
            if !CGEventSource.keyState(.combinedSessionState, key: 61) { break }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        guard !CGEventSource.keyState(.combinedSessionState, key: 61) else {
            throw VoiceError(message: "右Optionを離してから再試行してください。")
        }
        target.activate(options: [])
        try await Task.sleep(nanoseconds: 150_000_000)
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == target.processIdentifier else {
            throw VoiceError(message: "挿入先をアクティブにできませんでした。")
        }
        guard let source = CGEventSource(stateID: .combinedSessionState),
              let down = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false) else {
            throw VoiceError(message: "貼り付けイベントを作成できませんでした。")
        }
        let pasteboard = NSPasteboard.general
        let old = pasteboard.pasteboardItems?.map { item -> NSPasteboardItem in
            let copy = NSPasteboardItem()
            for type in item.types { if let data = item.data(forType: type) { copy.setData(data, forType: type) } }
            return copy
        } ?? []
        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else { throw VoiceError(message: "クリップボードに書き込めませんでした。") }
        let ownChange = pasteboard.changeCount
        down.flags = .maskCommand; up.flags = .maskCommand
        down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
        try? await Task.sleep(nanoseconds: 500_000_000)
        if restore && pasteboard.changeCount == ownChange {
            pasteboard.clearContents(); pasteboard.writeObjects(old)
        }
    }
}
