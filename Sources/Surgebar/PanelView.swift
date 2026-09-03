import SwiftUI
import AppKit

/// Height of the panel's scrolling content, reported up so the ScrollView can be
/// given a definite frame (see the comment in `body`).
private struct BodyHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

/// The panel shown when the menu-bar item is clicked. HIG-native: system
/// materials (the window provides them), SF Symbols, system fonts and colours.
/// At rest it's calm and monochrome; colour appears only under load.
struct PanelView: View {
    @ObservedObject var sampler: Sampler
    @ObservedObject var settings: TriageSettings
    @StateObject private var processes = ProcessMonitor()
    @Environment(\.openWindow) private var openWindow

    @State private var expandedPID: Int32?
    @State private var pending: PendingAction?
    @State private var toast: String?

    @State private var bodyHeight: CGFloat = 0
    @State private var adviceLoading = false
    @State private var adviceError: String?
    @State private var advice: [TriageRecommendation] = []

    struct PendingAction: Identifiable {
        let id = UUID()
        let action: ProcessAction
        let proc: PlainProcess
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            ScrollView {
                // Spacing groups these sections; they used to be separated by
                // rules, which stacked up against the header and footer rules
                // and made a 340pt panel look like a fence.
                VStack(alignment: .leading, spacing: 16) {
                    heroAdvice
                    summarySection
                    processSection
                    if let toast { toastView(toast) }
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 14)
                .background(
                    GeometryReader { geo in
                        Color.clear.preference(key: BodyHeightKey.self, value: geo.size.height)
                    }
                )
            }
            // A ScrollView has no intrinsic height and MenuBarExtra sizes its
            // window from the content's *ideal* height, so an unconstrained
            // ScrollView collapses to nothing — the panel showed only its header
            // and footer. Measuring the content and setting a definite height
            // fixes that while keeping the ScrollView's clipping intact: sizing
            // it with fixedSize instead let tall content (once AI advice loads)
            // draw straight over the header.
            .frame(height: bodyHeight > 0 ? min(bodyHeight, 560) : 320)
            .clipped()
            .onPreferenceChange(BodyHeightKey.self) { bodyHeight = $0 }
            Divider()
            footer
        }
        .frame(width: 340)
        .onAppear { processes.start() }
        .onDisappear { processes.stop() }
        .alert(pending.map { "\($0.action.title) \($0.proc.name)?" } ?? "",
               isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
               presenting: pending) { p in
            Button(p.action.title, role: .destructive) { perform(p.action, on: p.proc) }
            Button("Cancel", role: .cancel) { }
        } message: { p in
            Text(p.action.consequence)
        }
    }

    // MARK: - Header / footer

    private var header: some View {
        HStack {
            Text("surgebar").font(.headline)
            if processes.isRefreshing {
                ProgressView().controlSize(.small).padding(.leading, 2)
            }
            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.top, 10)
        .padding(.bottom, 8)
    }

    private var footer: some View {
        HStack {
            Button {
                NSApp.activate(ignoringOtherApps: true)
                openWindow(id: "settings")
            } label: {
                Label("Settings", systemImage: "gearshape")
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            Spacer()
            Button("Quit") { NSApplication.shared.terminate(nil) }
                .keyboardShortcut("q")
        }
        .controlSize(.small)
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    // MARK: - Summary (system CPU + memory)

    private var summarySection: some View {
        let snap = sampler.snapshot
        let cpu = level(forCPU: snap.cpuPercent)
        // CPU and memory are parallel facts, so they read side by side as one
        // ribbon rather than as two stacked rows with a chart wedged between.
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 0) {
                metric(title: "CPU", value: "\(Int(snap.cpuPercent.rounded()))%",
                       color: cpu == .normal ? .primary : cpu.color)
                Spacer(minLength: 12)
                metric(title: "Memory", value: "\(Int(snap.memoryUsedPercent.rounded()))%",
                       color: .primary, alignment: .trailing)
            }
            Sparkline(values: sampler.cpuHistory)
                .stroke(cpu == .normal ? Color.secondary : cpu.color,
                        style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
                .frame(height: 20)
                .accessibilityLabel("CPU history")
            HStack(spacing: 6) {
                Circle().fill(level(forPressure: snap.pressure).color).frame(width: 7, height: 7)
                Text(pressureLine(snap.pressure))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func metric(title: String, value: String, color: Color,
                        alignment: HorizontalAlignment = .leading) -> some View {
        VStack(alignment: alignment, spacing: 0) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value)
                .font(.system(.title2, design: .rounded).weight(.semibold))
                .foregroundStyle(color).monospacedDigit().contentTransition(.numericText())
        }
    }

    // MARK: - Process list

    private var processSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("What's using your Mac")
                .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            let shown = processes.processes.filter { $0.cpuPercent >= 0.5 }.prefix(6)
            if shown.isEmpty {
                Text("Nothing's working hard right now.")
                    .font(.callout).foregroundStyle(.secondary)
            } else {
                ForEach(Array(shown)) { proc in
                    ProcessRowView(
                        proc: proc,
                        isExpanded: expandedPID == proc.id,
                        onTap: { withAnimation(.easeInOut(duration: 0.15)) {
                            expandedPID = expandedPID == proc.id ? nil : proc.id
                        } },
                        onAction: { requestAction($0, on: proc) }
                    )
                }
            }
        }
    }

    // MARK: - AI advice (the hero — first thing you see)

    @ViewBuilder
    private var heroAdvice: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Proactive nudge: when the Mac is working hard, say so plainly up top.
            if overallLevel != .normal {
                Label(loadHeadline, systemImage: overallLevel == .critical ? "exclamationmark.triangle.fill" : "bolt.fill")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(overallLevel.color)
            }

            if !settings.isConfigured {
                notConfiguredHero
            } else if adviceLoading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Looking at what's running…").font(.callout).foregroundStyle(.secondary)
                }
            } else if advice.isEmpty {
                askButton
                if let adviceError {
                    Text(adviceError).font(.callout).foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } else {
                ForEach(advice) { rec in
                    RecommendationRow(rec: rec) {
                        if let action = rec.action, let pid = rec.pid,
                           let proc = processes.processes.first(where: { $0.id == pid }) {
                            requestAction(action, on: proc)
                        }
                    }
                }
                Button("Check again", systemImage: "arrow.clockwise") { askForAdvice() }
                    .controlSize(.small).padding(.top, 2)
            }
        }
    }

    private var askButton: some View {
        Button {
            askForAdvice()
        } label: {
            Label(overallLevel == .normal ? "What should I do?" : "What's slowing my Mac down?",
                  systemImage: "sparkles")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .tint(overallLevel == .critical ? .red : (overallLevel == .warning ? .orange : .accentColor))
    }

    private var notConfiguredHero: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Add your own AI key for a plain-English read on what's slowing things down.")
                .font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button {
                NSApp.activate(ignoringOtherApps: true)
                openWindow(id: "settings")
            } label: {
                Label("Turn on AI advice", systemImage: "sparkles").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    private func toastView(_ text: String) -> some View {
        Text(text)
            .font(.callout)
            .foregroundStyle(.secondary)
            .padding(.top, 2)
    }

    // MARK: - Actions

    private func requestAction(_ action: ProcessAction, on proc: PlainProcess) {
        if action.isDestructive {
            pending = PendingAction(action: action, proc: proc)
        } else {
            perform(action, on: proc)   // slow-down is safe — no confirmation needed
        }
    }

    private func perform(_ action: ProcessAction, on proc: PlainProcess) {
        switch ProcessControl.apply(action, to: proc) {
        case .done:              toast = action.doneMessage(proc.name)
        case .alreadyClosed:     toast = "\(proc.name) had already closed."
        case .notAllowed(let m): toast = m
        }
        advice.removeAll(where: { $0.pid == proc.id })
        Task { await processes.refresh() }
    }

    private func askForAdvice() {
        adviceLoading = true
        adviceError = nil
        let snapshot = sampler.snapshot
        let procs = processes.processes
        let config = settings.config
        Task {
            do {
                advice = try await TriageEngine.advise(system: snapshot, processes: procs, config: config)
                if advice.isEmpty { adviceError = "The AI didn't suggest anything specific. Your Mac is probably fine." }
            } catch {
                adviceError = (error as? TriageError)?.errorDescription ?? error.localizedDescription
            }
            adviceLoading = false
        }
    }

    // MARK: - Level helpers

    /// The worse of CPU load and memory pressure — drives the proactive nudge.
    private var overallLevel: SystemStatus.Level {
        let snap = sampler.snapshot
        let ranks: [SystemStatus.Level] = [.normal, .warning, .critical]
        let cpu = level(forCPU: snap.cpuPercent)
        let mem = level(forPressure: snap.pressure)
        return (ranks.firstIndex(of: cpu) ?? 0) >= (ranks.firstIndex(of: mem) ?? 0) ? cpu : mem
    }

    private var loadHeadline: String {
        switch overallLevel {
        case .critical: return "Your Mac is under heavy load right now."
        case .warning:  return "Your Mac's working hard right now."
        case .normal:   return ""
        }
    }

    private func level(forCPU cpu: Double) -> SystemStatus.Level {
        cpu >= 90 ? .critical : (cpu >= 65 ? .warning : .normal)
    }
    private func level(forPressure p: MemoryPressure) -> SystemStatus.Level {
        switch p { case .normal: return .normal; case .warning: return .warning; case .critical: return .critical }
    }
    private func pressureLine(_ p: MemoryPressure) -> String {
        switch p {
        case .normal:   return "Memory is comfortable"
        case .warning:  return "Memory is getting tight"
        case .critical: return "Memory is very tight"
        }
    }
}

// MARK: - One program in the list

private struct ProcessRowView: View {
    let proc: PlainProcess
    let isExpanded: Bool
    let onTap: () -> Void
    let onAction: (ProcessAction) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: onTap) {
                HStack(alignment: .top, spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(proc.name).font(.callout.weight(.medium)).foregroundStyle(.primary)
                        Text(proc.whatItIs)
                            .font(.caption).foregroundStyle(.secondary)
                            .lineLimit(isExpanded ? nil : 1)
                    }
                    Spacer(minLength: 8)
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("\(Int(proc.cpuPercent.rounded()))%")
                            .font(.callout.monospacedDigit().weight(.semibold))
                            .foregroundStyle(proc.cpuPercent >= 80 ? .primary : .secondary)
                        Text(proc.memoryText).font(.caption2).foregroundStyle(.secondary)
                    }
                    Image(systemName: "chevron.right")
                        .font(.caption2).foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(isExpanded ? 90 : 0))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isExpanded {
                if proc.isSystem {
                    Label("Part of macOS — best left alone.", systemImage: "lock.shield")
                        .font(.caption).foregroundStyle(.secondary)
                        .padding(.leading, 2)
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(ProcessAction.allCases, id: \.self) { action in
                            actionChoice(action)
                        }
                    }
                    .padding(.leading, 2)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func actionChoice(_ action: ProcessAction) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Button { onAction(action) } label: {
                Label(action.title, systemImage: icon(action))
            }
            .controlSize(.small)
            .tint(action.isDestructive ? .red : .accentColor)
            Text(action.consequence)
                .font(.caption2).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func icon(_ action: ProcessAction) -> String {
        switch action {
        case .slowDown:  return "tortoise"
        case .quit:      return "xmark.circle"
        case .forceQuit: return "exclamationmark.octagon"
        }
    }
}

// MARK: - CPU sparkline

/// Lightweight CPU sparkline (fixed 0–100 scale) — no charting dependency, to
/// keep the binary tiny.
struct Sparkline: Shape {
    var values: [Double]

    func path(in rect: CGRect) -> Path {
        var path = Path()
        guard values.count > 1 else { return path }
        let stepX = rect.width / CGFloat(values.count - 1)
        for (index, value) in values.enumerated() {
            let x = CGFloat(index) * stepX
            let y = rect.height * (1 - CGFloat(min(max(value, 0), 100) / 100))
            let point = CGPoint(x: x, y: y)
            if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
        }
        return path
    }
}

// MARK: - One AI recommendation

private struct RecommendationRow: View {
    let rec: TriageRecommendation
    let onDo: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: rec.kind == .info ? "info.circle" : "arrow.right.circle")
                    .foregroundStyle(rec.kind == .info ? Color.secondary : .accentColor)
                    .font(.callout)
                Text(rec.label).font(.callout.weight(.medium))
            }
            Text(rec.reason).font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if rec.action != nil {
                Button("Do it") { onDo() }
                    .controlSize(.small)
                    .tint(rec.kind == .forceQuit ? .red : .accentColor)
            }
        }
        .padding(.vertical, 3)
    }
}
