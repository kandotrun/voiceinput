import Foundation

/// Pure state machine. A short first tap never submits audio; a second tap starts hands-free.
struct KeyState {
    enum Mode: Equatable { case idle, held(TimeInterval), waiting(TimeInterval), handsFree, stopping }
    enum Action: Equatable { case start, stop, cancel }
    var mode: Mode = .idle
    let interval: TimeInterval = 0.350

    mutating func press(at time: TimeInterval) -> [Action] {
        switch mode {
        case .idle: mode = .held(time); return [.start]
        case .waiting(let first) where time - first <= interval:
            mode = .handsFree; return [.start]
        case .waiting: mode = .held(time); return [.start]
        case .handsFree: mode = .stopping; return [.stop]
        default: return []
        }
    }
    mutating func release(at time: TimeInterval) -> [Action] {
        switch mode {
        case .held(let start):
            if time - start < interval { mode = .waiting(start); return [.cancel] }
            mode = .idle; return [.stop]
        case .stopping: mode = .idle; return []
        default: return []
        }
    }
    mutating func cancel() -> [Action] {
        let active: Bool
        switch mode { case .held, .handsFree: active = true; default: active = false }
        mode = .idle
        return active ? [.cancel] : []
    }
}
