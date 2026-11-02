import Foundation

@main
struct NetworkTests {
    static func main() async throws {
        let base = CommandLine.arguments[1]
        let audio = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".wav")
        try Data("fixture-audio".utf8).write(to: audio)
        defer { try? FileManager.default.removeItem(at: audio) }
        let result = try await Transcriber.transcribe(file: audio, endpoint: base, correct: false, tokenProvider: { "test-only-token" })
        precondition(result == "テストの音声です")
        _ = try await Transcriber.transcribe(file: audio, endpoint: base + "/correct", correct: true, tokenProvider: { "test-only-token" })
        for path in ["/unauthorized", "/malformed", "/empty", "/redirect"] {
            do {
                _ = try await Transcriber.transcribe(file: audio, endpoint: base + path, correct: false, tokenProvider: { "test-only-token" })
                fatalError("Expected failure: \(path)")
            } catch is VoiceError { }
        }
        do {
            _ = try await Transcriber.transcribe(file: audio, endpoint: "file:///tmp", correct: false, tokenProvider: { fatalError("invalid URL must fail before reading token") })
            fatalError("invalid URL accepted")
        } catch is VoiceError { }
        print("PASS: multipart, correct on/off, JSON text, HTTP failure, malformed/empty response, redirect refusal, invalid URL")
    }
}
