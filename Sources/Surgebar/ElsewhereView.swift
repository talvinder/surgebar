import SwiftUI
import AppKit

struct ElsewhereView: View {
    @ObservedObject var model: ElsewhereModel
    @ObservedObject var settings: TriageSettings
    @State var tab = "Overview"
    @State private var draft = EWPermissionDraft()
    @State private var pending: Review?
    @State private var baselineDraft = EWPermissionDraft()
    @State private var draftTrust: EWJSON = .null
    @State private var draftConfig: Data?
    @State private var draftLoaded = false
    @State private var draftMessage: String?
    @State private var explaining = false
    @Environment(\.scenePhase) private var scenePhase
    private let tabs = ["Overview", "Activity", "Settings", "Installation"]
    struct Review: Identifiable {
        let id = UUID()
        let title: String
        let detail: String
        let arguments: [String]
        var config: Data? = nil
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Elsewhere").font(.headline)
                Spacer()
                if model.busy { ProgressView().controlSize(.small) }
                Button("Refresh", systemImage: "arrow.clockwise") { Task { await model.refresh() } }
                    .labelStyle(.iconOnly).buttonStyle(.borderless)
                    .help("Refresh Elsewhere").accessibilityLabel("Refresh Elsewhere")
                    .disabled(model.busy || pending != nil)
            }
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Scope").font(.caption).foregroundStyle(.secondary)
                    Text(model.directory.path).font(.callout).lineLimit(1).truncationMode(.middle).help(model.directory.path).textSelection(.enabled)
                }
                Spacer()
                Button("Change folder…") { chooseDirectory() }.buttonStyle(.borderless).controlSize(.small).disabled(model.busy || pending != nil)
            }
            if let error = model.error {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                if model.updated != nil { Text("Showing the last successful snapshot. It may be out of date.").font(.caption) }
            }
            if let notice = model.notice { Text(notice).font(.callout).foregroundStyle(.secondary) }
            Picker("View", selection: $tab) { ForEach(tabs, id: \.self) { Text($0).tag($0) } }
                .pickerStyle(.segmented)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if model.updated == nil {
                        ContentUnavailableView(model.executable == nil ? "Elsewhere not found" : "Waiting for Elsewhere", systemImage: "externaldrive", description: Text(model.executable == nil ? "Install Elsewhere to use these optional controls. Surgebar's Mac monitoring still works." : "Refresh to read this machine's current settings and work."))
                    } else {
                        selectedContent
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 4)
            }
            HStack {
                if let date = model.updated { Text("Last read \(date.formatted(date: .omitted, time: .standard))") }
                Spacer()
                Text("Times shown in " + (TimeZone.current.abbreviation() ?? "local time"))
            }.font(.caption).foregroundStyle(.secondary)
        }
        .padding(20).frame(minWidth: 580, idealWidth: 640, minHeight: 560, idealHeight: 660)
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                if pending == nil { await model.refresh() }
                do { try await Task.sleep(for: .seconds(10)) } catch { break }
            }
        }
        .onChange(of: model.directory) { _, _ in draftLoaded = false; draftConfig = nil; draftMessage = nil }
        .onChange(of: model.trust) { _, _ in
            if pending == nil && (!draftLoaded || draft == baselineDraft) { loadDraft() }
        }
        .sheet(item: $pending) { review in
            VStack(alignment: .leading, spacing: 16) {
                Text(review.title).font(.title2)
                ScrollView { Text(review.detail).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                HStack {
                    Button("Cancel") { pending = nil }.keyboardShortcut(.cancelAction)
                    Spacer()
                    Button("Confirm change") {
                        pending = nil
                        Task {
                            let saved = await model.perform(review.arguments, expectedConfig: review.config)
                            if saved && review.config != nil { loadDraft() }
                        }
                    }.keyboardShortcut(.defaultAction)
                }
            }.padding(24).frame(width: 550, height: 430)
        }
    }
    @ViewBuilder var selectedContent: some View {
        switch tab {
        case "Activity": work
        case "Settings": permissions
        case "Installation": installation
        default: overview
        }
    }
    private var overview: some View {
        let c = model.queue["capacity"]
        return VStack(alignment: .leading, spacing: 16) {
            Text(c["capacity_band"]["reason"].text).font(.headline)
            GroupBox("Capacity reported by Elsewhere") {
                VStack(spacing: 9) {
                    row("Available for new work", c["budget"]["available_mb"].text + " MB")
                    row("Protected system reserve", c["budget"]["reserve_mb"].text + " MB")
                    row("Live swap activity", c["capacity_band"]["swap_activity_mb_per_second"].text + " MB/s")
                    row("New builds / tests", c["recommendations"]["build"].text + " / " + c["recommendations"]["test"].text)
                    row("New parallel agents", c["recommendations"]["parallel-agent"].text)
                }.padding(8)
            }
            GroupBox("Remote placement") {
                VStack(alignment: .leading, spacing: 9) {
                    row("First provider", model.providers["routing"]["default"].text)
                    row("Fallbacks", model.providers["routing"]["fallbacks"].strings.joined(separator: " → ").nonempty("None"))
                    row("Execution permission", model.trust["valid"].yes ? "Valid" : "Not ready")
                    Text("Local ‘run’ jobs stay local. An agent must assess placement and explicitly request remote execution.").foregroundStyle(.secondary)
                    ForEach(model.trust["reasons"].strings, id: \.self) { Text($0).foregroundStyle(.orange) }
                }.padding(8)
            }
            DisclosureGroup("Why can work wait when memory is available?") {
                Text("Elsewhere also checks existing reservations, workload concurrency, live paging and the resources requested by the job. Read each job's recorded reason in Activity. Capacity ceilings are Elsewhere rules, not Surgebar preferences.").padding(.top, 8)
            }
            if settings.isConfigured {
                Button(explaining ? "Explaining…" : "Explain this capacity snapshot with AI", systemImage: "sparkles") {
                    explaining = true
                    let summary = model.aiSummary
                    let config = settings.config
                    Task {
                        do { model.advice = try await TriageEngine.explainElsewhere(summary: summary, config: config) }
                        catch { model.advice = error.localizedDescription }
                        explaining = false
                    }
                }.disabled(explaining)
                Text("Sends only the capacity numbers shown here to your configured AI. No job commands, paths, account details or permissions.").font(.caption).foregroundStyle(.secondary)
                if let advice = model.advice { Text(advice).textSelection(.enabled) }
            }
        }
    }
    private var work: some View {
        VStack(alignment: .leading, spacing: 16) {
            ForEach(Array(model.queue["placement_opportunities"].array.enumerated()), id: \.offset) { _, opportunity in
                GroupBox("Placement review needed · " + opportunity["owner"].text) {
                    Text(opportunity["message"].text).frame(maxWidth: .infinity, alignment: .leading).padding(6)
                }
            }
            Text("Jobs").font(.headline)
            if model.queue["active_jobs"].array.isEmpty { Text("No waiting or running jobs in Elsewhere's ledger.").foregroundStyle(.secondary) }
            ForEach(Array(model.queue["active_jobs"].array.enumerated()), id: \.offset) { _, job in jobRow(job) }
            Text("Reservations").font(.headline)
            ForEach(Array(model.queue["leases"].array.enumerated()), id: \.offset) { _, lease in
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        row(lease["owner"].text, lease["reserved_mb"].text + " MB")
                        Text(lease["workload"].text + " · " + lease["count"].text + " slots").foregroundStyle(.secondary)
                        if lease["tracked_job_id"] == .null, let token = lease["token"].string {
                            Button("Release reservation…") {
                                pending = Review(title: "Release this reservation?", detail: "Owner: \(lease["owner"].text)\nWorkload: \(lease["workload"].text)\n\nThis removes its capacity reservation. It does not stop the underlying process. Release it only when that work is finished or no longer needs the reservation.", arguments: ["release", token])
                            }.disabled(model.busy)
                        }
                    }.padding(4)
                }
            }
            Text("Recent activity").font(.headline)
            if model.recentJobs.isEmpty { Text("No recent jobs recorded.").foregroundStyle(.secondary) }
            ForEach(Array(model.recentJobs.enumerated()), id: \.offset) { _, job in jobRow(job) }
            Text("This is the local ledger. Remote lifecycle states are those last recorded by Elsewhere.").font(.caption).foregroundStyle(.secondary)
        }
    }
    private func jobRow(_ job: EWJSON) -> some View {
        let activity = EWActivity(job: job)
        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: activity.symbol)
                .font(.title3).foregroundStyle(activity.failed ? Color.orange : Color.secondary)
                .frame(width: 22).padding(.top, 2)
            VStack(alignment: .leading, spacing: 5) {
                row(job["owner"].text, activity.title)
                Text(activity.timestampText).font(.caption).foregroundStyle(.secondary)
                Text(job["provider"].text + " · " + job["workload"].text).font(.caption).foregroundStyle(.secondary)
                Text(model.failureDetails[job["id"].text] ?? activity.explanation)
                    .font(.callout).fixedSize(horizontal: false, vertical: true)
                if activity.state == "cleaned", job["completed_at"].number != nil {
                    Text("Time shown is work completion; cleanup time was not recorded.").font(.caption).foregroundStyle(.secondary)
                }
                if activity.failed {
                    Button("Check failure detail") { Task { await model.inspectFailure(job) } }
                        .buttonStyle(.borderless).controlSize(.small).disabled(model.busy)
                }
                if job["can_cancel"].yes, let id = job["id"].string {
                    Button("Cancel job…") {
                        pending = Review(title: "Cancel this job?", detail: "Owner: \(job["owner"].text)\nProvider: \(job["provider"].text)\nState: \(activity.title)\nJob: \(id)\n\nElsewhere will cancel this queued or running job. In-progress work may stop. This does not request result deletion or resource cleanup.", arguments: ["job-cancel", id])
                    }.buttonStyle(.borderless).controlSize(.small).disabled(model.busy)
                }
                Divider().padding(.top, 8)
            }
        }
    }
    private var permissions: some View {
        VStack(alignment: .leading, spacing: 20) {
            section("Source access") {
                Toggle(isOn: Binding(get: { draft.allowPrivate ?? model.trust["source"]["allow_private"].yes }, set: { draft.allowPrivate = $0 })) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Allow private repositories")
                        Text("Permit source from private repositories in the approved folders.").font(.caption).foregroundStyle(.secondary)
                    }
                }.toggleStyle(.switch).disabled(model.editableConfig == nil)
                Toggle(isOn: Binding(get: { draft.allowUncommitted ?? model.trust["source"]["allow_uncommitted"].yes }, set: { draft.allowUncommitted = $0 })) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Allow uncommitted changes")
                        Text("Include local edits that haven’t been committed yet.").font(.caption).foregroundStyle(.secondary)
                    }
                }.toggleStyle(.switch).disabled(model.editableConfig == nil)
                Text("Approved folders").font(.caption).foregroundStyle(.secondary)
                ForEach(model.trust["source"]["allowed_roots"].strings, id: \.self) { Text($0).font(.callout).textSelection(.enabled) }
            }
            section("Limits for each job") {
                if model.editableConfig != nil {
                    numberField("CPU cores", value: $draft.cpu)
                    numberField("Memory (MB)", value: $draft.memory)
                    numberField("Runtime (seconds)", value: $draft.seconds)
                    HStack { Text("Estimated cost (USD)"); Spacer(); TextField("Cost", value: $draft.cost, format: .number).frame(width: 120) }
                    numberField("Valid for after saving (days)", value: $draft.days)
                } else {
                    row("CPU cores", model.trust["limits"]["max_cpu"].text)
                    row("Memory (MB)", model.trust["limits"]["max_memory_mb"].text)
                    row("Runtime (seconds)", model.trust["limits"]["max_runtime_seconds"].text)
                    row("Estimated cost (USD)", model.trust["limits"]["max_estimated_cost_usd"].text)
                }
                row("Current expiry", model.trust["expires_at"].text)
            }
            if model.editableConfig != nil {
                HStack {
                    Text(draft != baselineDraft ? "Unsaved changes" : "Changes are reviewed before saving").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Discard") { loadDraft() }.disabled(draft == baselineDraft)
                    Button("Review changes…") { reviewPermission() }.disabled(model.busy || draft == baselineDraft)
                }.controlSize(.small)
            } else {
                Text("These permissions are inherited or aren’t currently valid. Open their owning configuration to change them.").font(.callout).foregroundStyle(.secondary)
            }
            if let draftMessage {
                Text(draftMessage).foregroundStyle(.orange)
                Button("Reload settings") { loadDraft() }.controlSize(.small)
            }
            section("Providers") {
                ForEach(model.providers["providers"].object.keys.sorted(), id: \.self) { name in
                    let provider = model.providers["providers"][name]
                    row(name.capitalized, provider["ready"].yes ? "Ready" : "Needs attention")
                    Text(model.trust["providers"][name]["regions"].strings.joined(separator: ", ").nonempty("No approved regions")).font(.caption).foregroundStyle(.secondary)
                }
                Text("Readiness is a status check, not a setting. Provider order, regions and storage are in the configuration file.").font(.caption).foregroundStyle(.secondary)
                if let url = model.configURL {
                    Button("Advanced configuration…") { NSWorkspace.shared.open(url) }.buttonStyle(.borderless)
                    Text(url.path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                }
            }
        }.onAppear { if !draftLoaded { loadDraft() } }
    }
    private func loadDraft() {
        let l = model.trust["limits"]
        draft = EWPermissionDraft()
        draft.cpu = Int(l["max_cpu"].number ?? 4); draft.memory = Int(l["max_memory_mb"].number ?? 8192)
        draft.seconds = Int(l["max_runtime_seconds"].number ?? 3600); draft.cost = l["max_estimated_cost_usd"].number ?? 5
        draft.allowPrivate = model.trust["source"]["allow_private"].yes
        draft.allowUncommitted = model.trust["source"]["allow_uncommitted"].yes
        baselineDraft = draft; draftTrust = model.trust; draftConfig = model.editableConfig
        draftLoaded = true; draftMessage = nil
    }
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.subheadline.weight(.medium)).foregroundStyle(.secondary)
            content()
        }
    }
    private var installation: some View {
        VStack(alignment: .leading, spacing: 16) {
            row("Runtime", model.version)
            Text(model.executable?.path ?? "Unavailable").textSelection(.enabled)
            Text("Resolved executable: " + (model.executable?.resolvingSymlinksInPath().path ?? "Unavailable")).font(.caption).textSelection(.enabled)
            ForEach(Array(model.doctor["checks"].array.enumerated()), id: \.offset) { _, check in
                VStack(alignment: .leading, spacing: 5) {
                    row(check["name"].text, check["status"].text)
                    Text(check["message"].text).foregroundStyle(.secondary)
                    if let next = check["next"].string { Text(next).font(.caption).textSelection(.enabled) }
                }
                Divider()
            }
            Text("The executable reports these diagnostics. Surgebar does not certify its binary contents or install an update.").font(.caption).foregroundStyle(.secondary)
        }
    }
    private func reviewPermission() {
        guard let config = draftConfig, let path = model.configURL?.path,
              draftTrust == model.trust, config == model.editableConfig else {
            draftMessage = "The configuration changed while you were editing. Reload settings before saving."
            return
        }
        do {
            let args = try draft.arguments(path: path, trust: model.trust)
            let destinations = model.trust["providers"].object.keys.sorted().map { name in
                let p = model.trust["providers"][name]
                return name + ": " + p["regions"].strings.joined(separator: ", ") + "\n" + p["identity"].object.keys.sorted().map { "  \($0): \(p["identity"][$0].text)" }.joined(separator: "\n")
            }.joined(separator: "\n")
            let storage = model.trust["artifact_store"].object.keys.sorted().map { "\($0): \(model.trust["artifact_store"][$0].text)" }.joined(separator: "\n")
            pending = Review(title: "Save and renew this permission?", detail: "Configuration: \(path)\n\nDestinations:\n\(destinations)\n\nArtifact storage:\n\(storage)\n\nSource roots:\n\(model.trust["source"]["allowed_roots"].strings.joined(separator: "\n"))\nPrivate repositories: \(model.trust["source"]["allow_private"].text) → \((draft.allowPrivate ?? false) ? "Yes" : "No")\nUncommitted changes: \(model.trust["source"]["allow_uncommitted"].text) → \((draft.allowUncommitted ?? false) ? "Yes" : "No")\n\nNew ceilings: \(draft.cpu) cores, \(draft.memory) MB, \(draft.seconds) seconds, $\(draft.cost) estimated cost per job.\nNew expiry: \(draft.days) days from confirmation.\n\nElsewhere will save a new permission receipt. No cloud work starts.", arguments: args, config: config)
        } catch { draftMessage = error.localizedDescription }
    }
    private func chooseDirectory() {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { model.selectDirectory(url); Task { await model.refresh() } }
    }
    private func numberField(_ title: String, value: Binding<Int>) -> some View {
        HStack { Text(title); Spacer(); TextField(title, value: value, format: .number).frame(width: 120) }
    }
    private func row(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top) { Text(title); Spacer(minLength: 16); Text(value).foregroundStyle(.secondary).multilineTextAlignment(.trailing).textSelection(.enabled) }
    }
}
private extension String { func nonempty(_ fallback: String) -> String { isEmpty ? fallback : self } }
