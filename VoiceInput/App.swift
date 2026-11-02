import SwiftUI
import AppKit
import AVFoundation
import ApplicationServices
import UserNotifications
import ServiceManagement

@main
struct VoiceInputApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene { Settings { SettingsView(model: delegate.model) } }
}

@MainActor
final class Model: ObservableObject {
    @Published var endpoint = UserDefaults.standard.string(forKey: "endpoint") ?? "http://100.72.208.31:8791" {
        didSet { UserDefaults.standard.set(endpoint, forKey: "endpoint") }
    }
    @Published var correct = UserDefaults.standard.object(forKey: "correct") as? Bool ?? false {
        didSet { UserDefaults.standard.set(correct, forKey: "correct") }
    }
    @Published var restore = UserDefaults.standard.object(forKey: "restore") as? Bool ?? true {
        didSet { UserDefaults.standard.set(restore, forKey: "restore") }
    }
    @Published var indicator = UserDefaults.standard.object(forKey: "indicator") as? Bool ?? true {
        didSet { UserDefaults.standard.set(indicator, forKey: "indicator") }
    }
    @Published var status = "待機中"
    @Published var microphone = false
    @Published var accessibility = false
    @Published var monitoring = false
    @Published var retries: [URL] = []
    @Published var busy = false
    @Published var login = false
    var retry: ((URL) -> Void)?
    var reconnect: (() -> Void)?
    func refresh() {
        microphone = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        accessibility = AXIsProcessTrusted()
        monitoring = CGPreflightListenEventAccess()
        login = SMAppService.mainApp.status == .enabled
        retries = ((try? FileManager.default.contentsOfDirectory(at: Recorder.recordings, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.pathExtension == "wav" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }
    func requestMicrophone() {
        AVCaptureDevice.requestAccess(for: .audio) { _ in Task { @MainActor in self.refresh() } }
    }
    func openPrivacy(_ anchor: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)") { NSWorkspace.shared.open(url) }
    }
    func setLogin(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch { status = "ログイン起動を変更できません。システム設定を確認してください。" }
        refresh()
    }
}

struct SettingsView: View {
    @ObservedObject var model: Model
    @State private var token = ""
    @State private var tokenMessage = ""
    var body: some View {
        Form {
            Text("voiceinput 設定").font(.title2)
            TextField("エンドポイントURL", text: $model.endpoint)
            Text("ベースURLを指定します。末尾の /transcribe は自動で追加します。")
                .font(.caption).foregroundColor(.secondary)
            SecureField("上書きトークン（空欄で.env参照）", text: $token)
            HStack {
                Button("トークンを保存") {
                    do { try TokenStore.save(token); token = ""; tokenMessage = "保存しました（空欄の場合は.env参照）。" }
                    catch { tokenMessage = error.localizedDescription }
                }
                Text(tokenMessage).font(.caption)
            }
            Text("既定: ~/transcribe-endpoint/.env の TRANSCRIBE_TOKEN。上書きはキーチェーンに保存します。")
                .font(.caption)
            Toggle("辞書・LLM補正を使用する（correct）", isOn: $model.correct)
            Toggle("貼り付け後にクリップボードを復元する", isOn: $model.restore)
            Toggle("録音中インジケータを表示する", isOn: $model.indicator)
            Toggle("ログイン時に起動する", isOn: Binding(get: { model.login }, set: { model.setLogin($0) }))
            Divider()
            Text("右Option長押し: 録音 → 離して挿入\n350ms以内に短押し2回: ハンズフリー → もう一度押して挿入\n他のキー・Esc: 録音キャンセル").font(.callout)
            HStack {
                Text("マイク: \(model.microphone ? "許可済み" : "未許可")")
                Button("許可する") { model.requestMicrophone() }
                Button("設定を開く") { model.openPrivacy("Privacy_Microphone") }
            }
            HStack {
                Text("アクセシビリティ: \(model.accessibility ? "許可済み" : "未許可")")
                Button("設定を開く") { model.openPrivacy("Privacy_Accessibility") }
            }
            HStack {
                Text("入力監視: \(model.monitoring ? "許可済み" : "未許可")")
                Button("設定を開く") { model.openPrivacy("Privacy_ListenEvent") }
            }
            Button("権限を再確認・キー監視を再接続") { model.refresh(); model.reconnect?() }
            Divider()
            Text(model.status).textSelection(.enabled)
            HStack {
                Text("再試行用音声（失敗・中断時に保持）")
                Button("保存場所を開く") {
                    try? FileManager.default.createDirectory(at: Recorder.recordings, withIntermediateDirectories: true)
                    NSWorkspace.shared.open(Recorder.recordings)
                }
                Button("更新") { model.refresh() }
            }
            ScrollView {
                VStack(alignment: .leading) {
                    ForEach(model.retries, id: \.self) { url in
                        HStack {
                            Text(url.lastPathComponent).font(.caption)
                            Button("文字起こしを再試行") { model.retry?(url) }.disabled(model.busy)
                        }
                    }
                }
            }.frame(height: 90)
            Text("再試行結果はコピーされます。目的のアプリで貼り付けてください。保存音声はFinderから削除できます。")
                .font(.caption)
        }.padding(20).frame(width: 650).onAppear { model.refresh() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let model = Model()
    private var statusItem: NSStatusItem!
    private var settingsWindow: NSWindow?
    private var panel: NSPanel?
    private var tap: CFMachPort?
    private var source: CFRunLoopSource?
    private var keys = KeyState()
    private var rightDown = false
    private let recorder = Recorder()
    private var recording = false
    private var target: NSRunningApplication?
    private var work: Task<Void, Never>?
    private var observers: [NSObjectProtocol] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "mic", accessibilityDescription: "音声入力")
        let menu = NSMenu()
        menu.addItem(withTitle: "設定・再試行用音声…", action: #selector(showSettings), keyEquivalent: ",").target = self
        menu.addItem(withTitle: "録音をキャンセル", action: #selector(cancelRecording), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "終了", action: #selector(quit), keyEquivalent: "q").target = self
        statusItem.menu = menu
        model.retry = { [weak self] url in self?.submit(url, target: nil) }
        model.reconnect = { [weak self] in self?.connectKeys() }
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
        model.refresh(); connectKeys()
        observers.append(NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.cancelRecording() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.cancelRecording() }
        })
        if !model.microphone || !model.accessibility || tap == nil {
            showSettings()
            let alert = NSAlert()
            alert.messageText = "音声入力に必要な権限"
            alert.informativeText = "設定画面でマイクとアクセシビリティを許可してください。キー監視が開始できない場合は入力監視も許可し、再接続してください。"
            alert.addButton(withTitle: "設定する"); alert.runModal()
            if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined { model.requestMicrophone() }
        }
    }
    @objc func showSettings() {
        if settingsWindow == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 690, height: 680),
                                  styleMask: [.titled, .closable], backing: .buffered, defer: false)
            window.title = "voiceinput 設定"; window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: SettingsView(model: model)); window.center()
            settingsWindow = window
        }
        model.refresh(); NSApp.activate(ignoringOtherApps: true); settingsWindow?.makeKeyAndOrderFront(nil)
    }
    @objc func quit() { cancelRecording(); work?.cancel(); NSApp.terminate(nil) }
    @objc func cancelRecording() {
        _ = keys.cancel(); rightDown = false
        if recording { _ = recorder.finish(discard: true); recording = false }
        panel?.orderOut(nil)
        if !model.busy { model.status = "録音をキャンセルしました"; updateIcon("mic") }
    }
    private func updateIcon(_ name: String) {
        statusItem.button?.image = NSImage(systemSymbolName: name, accessibilityDescription: model.status)
        statusItem.button?.toolTip = model.status
    }
    func connectKeys() {
        cancelRecording()
        if let tap { CGEvent.tapEnable(tap: tap, enable: false) }
        if let source { CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes) }
        tap = nil; source = nil
        guard AXIsProcessTrusted() else { model.status = "アクセシビリティを許可してください"; return }
        let mask = (1 << CGEventType.flagsChanged.rawValue) | (1 << CGEventType.keyDown.rawValue)
        tap = CGEvent.tapCreate(tap: .cgSessionEventTap, place: .headInsertEventTap, options: .listenOnly,
                               eventsOfInterest: CGEventMask(mask), callback: { _, type, event, info in
            guard let info else { return Unmanaged.passUnretained(event) }
            // Source is attached exclusively to the main run loop.
            MainActor.assumeIsolated {
                Unmanaged<AppDelegate>.fromOpaque(info).takeUnretainedValue().handle(type, event)
            }
            return Unmanaged.passUnretained(event)
        }, userInfo: Unmanaged.passUnretained(self).toOpaque())
        guard let tap else { model.status = "キー監視を開始できません。入力監視を許可して再接続してください。"; return }
        source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        model.status = "待機中"
    }
    private func handle(_ type: CGEventType, _ event: CGEvent) {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            cancelRecording(); if let tap { CGEvent.tapEnable(tap: tap, enable: true) }; return
        }
        let code = event.getIntegerValueField(.keyboardEventKeycode)
        if type == .keyDown {
            if recording || code == 53 { cancelRecording() }
            else { _ = keys.cancel() }
            return
        }
        guard type == .flagsChanged else { return }
        guard code == 61 else { _ = keys.cancel(); if recording { cancelRecording() }; return }
        // Device-specific right-option flag, unlike maskAlternate, distinguishes left+right Option.
        let down = event.flags.rawValue & 0x40 != 0
        guard down != rightDown else { return }
        rightDown = down
        if down && (!event.flags.intersection([.maskCommand, .maskControl, .maskShift]).isEmpty || event.flags.rawValue & 0x20 != 0) { cancelRecording(); return }
        let now = Double(event.timestamp) / 1_000_000_000
        let actions = down ? keys.press(at: now) : keys.release(at: now)
        for action in actions {
            switch action {
            case .start: startRecording()
            case .stop: stopRecording()
            case .cancel:
                if recording { _ = recorder.finish(discard: true); recording = false }
                panel?.orderOut(nil); model.status = "待機中"; updateIcon("mic")
            }
        }
    }
    private func startRecording() {
        guard !model.busy else { _ = keys.cancel(); return }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            _ = keys.cancel(); model.status = "マイクを許可してください"; showSettings(); return
        }
        target = NSWorkspace.shared.frontmostApplication
        do {
            try recorder.start(); recording = true
            model.status = "録音中（Escでキャンセル）"; updateIcon("mic.fill")
            if model.indicator { showIndicator() }
        } catch { _ = keys.cancel(); fail("録音を開始できませんでした。マイクを確認してください。") }
    }
    private func showIndicator() {
        if panel == nil {
            let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 230, height: 44),
                            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            p.level = .floating; p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            p.isOpaque = false; p.backgroundColor = .clear; p.ignoresMouseEvents = true
            p.contentView = NSHostingView(rootView: HStack {
                Circle().fill(Color.red).frame(width: 10, height: 10)
                Text("録音中 · Escでキャンセル").font(.system(size: 13))
            }.padding(12).background(.regularMaterial).cornerRadius(12))
            panel = p
        }
        if let screen = NSScreen.main {
            panel?.setFrameOrigin(NSPoint(x: screen.visibleFrame.midX - 115, y: screen.visibleFrame.minY + 50))
        }
        panel?.orderFrontRegardless()
    }
    private func stopRecording() {
        guard recording else { return }
        recording = false; panel?.orderOut(nil)
        guard let result = recorder.finish() else { return }
        if result.failed { fail("録音の書き込みに失敗しました。再試行用音声を確認してください。"); return }
        guard result.valid else { model.status = "短い音声・無音のため破棄しました"; updateIcon("mic"); return }
        submit(result.url, target: target)
    }
    private func submit(_ url: URL, target: NSRunningApplication?) {
        guard !model.busy && !recording else { return }
        model.busy = true; model.status = "文字起こし中…"; updateIcon("ellipsis.bubble")
        let endpoint = model.endpoint, correct = model.correct, restore = model.restore
        work = Task { @MainActor in
            defer { model.busy = false; model.refresh(); updateIcon("mic"); work = nil }
            do {
                let text = try await Transcriber.transcribe(file: url, endpoint: endpoint, correct: correct)
                try Task.checkCancellation()
                // Keep a text sidecar if insertion fails; never include server bodies in errors.
                let sidecar = url.deletingPathExtension().appendingPathExtension("txt")
                try text.write(to: sidecar, atomically: true, encoding: .utf8)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: sidecar.path)
                if let target {
                    try await Paster.insert(text, target: target, restore: restore)
                    model.status = "挿入しました（貼り付け非対応のアプリでは設定の保存場所にあるテキストを利用できます）"
                } else {
                    NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
                    model.status = "再試行結果をコピーしました。目的のアプリで貼り付けてください。"
                    notify("文字起こし結果をコピーしました。目的のアプリで貼り付けてください。")
                }
                try FileManager.default.removeItem(at: url)
            } catch is CancellationError {
                model.status = "処理を中断しました。音声は再試行用に保持しました。"
            } catch {
                let message = (error as? VoiceError)?.message ?? "通信または保存・貼り付けに失敗しました。接続と権限を確認してください。"
                fail(message + " 音声は設定の「再試行用音声」に保持しています。")
            }
        }
    }
    private func fail(_ message: String) { model.status = message; model.refresh(); updateIcon("exclamationmark.mic"); notify(message) }
    private func notify(_ message: String) {
        let content = UNMutableNotificationContent(); content.title = "voiceinput"; content.body = message
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                           withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
