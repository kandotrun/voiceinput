import Foundation

/// Pure state machine. A short first tap never submits audio; a second tap starts hands-free.
struct KeyState {
    enum Mode: Equatable { case idle, held(TimeInterval), waiting(TimeInterval), secondHeld(TimeInterval), handsFree, stopping }
    enum Action: Equatable { case start, stop, cancel }
    var mode: Mode = .idle
    let interval: TimeInterval = 0.350

    mutating func press(at time: TimeInterval) -> [Action] {
        switch mode {
        case .idle: mode = .held(time); return [.start]
        case .waiting(let first) where time - first <= interval + 1e-9:
            mode = .secondHeld(time); return [.start]
        case .waiting: mode = .held(time); return [.start]
        case .handsFree: mode = .stopping; return [.stop]
        default: return []
        }
    }
    mutating func release(at time: TimeInterval) -> [Action] {
        switch mode {
        case .held(let start):
            if time - start + 1e-9 < interval { mode = .waiting(start); return [.cancel] }
            mode = .idle; return [.stop]
        case .secondHeld(let start):
            if time - start + 1e-9 < interval { mode = .handsFree; return [] }
            mode = .idle; return [.stop]
        case .stopping: mode = .idle; return []
        default: return []
        }
    }
    mutating func cancel() -> [Action] {
        let active: Bool
        switch mode { case .held, .secondHeld, .handsFree: active = true; default: active = false }
        mode = .idle
        return active ? [.cancel] : []
    }
}
