import Foundation

var checks = 0
func expect(_ result: Bool, _ message: String) {
    checks += 1
    if !result { fatalError(message) }
}
var key = KeyState()
expect(key.press(at: 0) == [.start], "hold starts immediately")
expect(key.release(at: 0.6) == [.stop], "hold release submits")
expect(key.mode == .idle, "hold resets")
expect(key.press(at: 1) == [.start], "first tap starts provisional recording")
expect(key.release(at: 1.05) == [.cancel], "first short tap discards audio")
expect(key.press(at: 1.2) == [.start], "second tap begins hands-free")
expect(key.mode == .secondHeld(1.2), "second press pending short release")
expect(key.release(at: 1.25).isEmpty, "second release must not submit")
expect(key.mode == .handsFree, "second short release confirms hands-free")
expect(key.press(at: 3) == [.stop], "third press submits once")
expect(key.release(at: 3.1).isEmpty, "third release no duplicate")
expect(key.press(at: 4) == [.start], "next recording")
expect(key.cancel() == [.cancel], "Option chord or Esc cancels")
expect(key.release(at: 4.8).isEmpty, "cancelled release no submission")
_ = key.press(at: 5); _ = key.release(at: 5.05)
expect(key.press(at: 5.351) == [.start], "expired double tap becomes new hold")
expect(key.mode == .held(5.351), "double interval measured press to press")
expect(key.release(at: 5.8) == [.stop], "expired second press can hold")
_ = key.press(at: 6); _ = key.release(at: 6.05); _ = key.press(at: 6.2); _ = key.release(at: 6.25)
expect(key.cancel() == [.cancel], "hands-free Esc cancels")
expect(key.press(at: 7) == [.start], "cancel resets cleanly")
expect(key.release(at: 7.35) == [.stop], "350ms boundary is a hold")
print("PASS: \(checks) key state assertions")

_ = key.press(at: 8); _ = key.release(at: 8.05); _ = key.press(at: 8.2)
expect(key.release(at: 8.8) == [.stop], "long second press is PTT, not hands-free")
expect(key.mode == .idle, "long second press resets")
print("PASS: second-long-press regression")
