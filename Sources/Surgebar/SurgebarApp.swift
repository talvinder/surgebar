import SwiftUI
import AppKit

@main
struct SurgebarApp: App {
    @StateObject private var sampler = Sampler()
    @StateObject private var settings = TriageSettings()

    // No Dock icon / app menu — configured via `LSUIElement` in Info.plist.
    // (Setting the activation policy in `init` traps: NSApp is nil that early.)

    var body: some Scene {
        MenuBarExtra {
            PanelView(sampler: sampler, settings: settings)
        } label: {
            // HIG: the menu-bar extra is a monochrome, template glyph that
            // adapts to the bar's appearance. State is conveyed by the gauge
            // level (and an alert glyph under pressure), not by colour.
            let status = SystemStatus(snapshot: sampler.snapshot)
            Image(systemName: status.menuSymbol)
            Text("\(Int(sampler.snapshot.cpuPercent.rounded()))%")
        }
        .menuBarExtraStyle(.window)

        Window("surgebar Settings", id: "settings") {
            SettingsView(settings: settings)
        }
        .windowResizability(.contentSize)
    }
}

/// Derives a single semantic level from CPU + memory pressure.
struct SystemStatus {
    let snapshot: SystemSnapshot

    enum Level { case normal, warning, critical }

    var level: Level {
        if snapshot.pressure == .critical || snapshot.cpuPercent >= 90 { return .critical }
        if snapshot.pressure == .warning || snapshot.cpuPercent >= 65 { return .warning }
        return .normal
    }

    /// Monochrome menu-bar glyph — gauge level at rest, alert under pressure.
    var menuSymbol: String {
        switch level {
        case .normal:   return "gauge.with.dots.needle.33percent"
        case .warning:  return "gauge.with.dots.needle.67percent"
        case .critical: return "gauge.with.dots.needle.100percent"
        }
    }
}

extension SystemStatus.Level {
    /// Semantic colour, used only inside the panel (HIG allows it there).
    var color: Color {
        switch self {
        case .normal:   return .green
        case .warning:  return .orange
        case .critical: return .red
        }
    }
}
