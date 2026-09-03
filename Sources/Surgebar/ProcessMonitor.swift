import Foundation

/// Feeds the "What's using your Mac" list. Only samples while the panel is open,
/// off the main thread, so it never makes the UI stutter and costs nothing at rest.
@MainActor
final class ProcessMonitor: ObservableObject {
    @Published private(set) var processes: [PlainProcess] = []
    @Published private(set) var isRefreshing = false

    private var loop: Task<Void, Never>?

    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(nanoseconds: 2_500_000_000)
            }
        }
    }

    func stop() {
        loop?.cancel()
        loop = nil
    }

    func refresh() async {
        isRefreshing = true
        // Sample + name off the main thread; hand back a ready-to-render list.
        let described = await Task.detached(priority: .userInitiated) { () -> [PlainProcess] in
            let raw = await ProcessSampler.sample(limit: 8)
            return raw.map(PlainLanguage.describe)
        }.value
        processes = described
        isRefreshing = false
    }
}
