import Foundation

/// A running program described the way a non-technical person would understand it:
/// a name they recognise, a plain sentence saying what it is, and whether it's
/// something macOS needs (so we never offer to stop it).
struct PlainProcess: Identifiable, Equatable {
    let raw: RunningProcess
    var id: Int32 { raw.id }
    let name: String        // "Google Chrome", "Spotlight", "Zoom"
    let whatItIs: String     // one plain sentence, no jargon
    let isSystem: Bool       // part of macOS — leave it alone

    var cpuPercent: Double { raw.cpuPercent }
    var memoryBytes: UInt64 { raw.memoryBytes }

    /// e.g. "1.2 GB" / "340 MB" — never bytes.
    var memoryText: String {
        let mb = Double(raw.memoryBytes) / (1024 * 1024)
        if mb >= 1024 { return String(format: "%.1f GB", mb / 1024) }
        return "\(Int(mb.rounded())) MB"
    }
}

/// The three things you can do to a program, each with a plain-English consequence.
enum ProcessAction: CaseIterable {
    case slowDown, quit, forceQuit

    var title: String {
        switch self {
        case .slowDown:  return "Slow it down"
        case .quit:      return "Quit it"
        case .forceQuit: return "Force quit"
        }
    }

    /// What actually happens, in words anyone can act on. No PIDs, no signals.
    var consequence: String {
        switch self {
        case .slowDown:
            return "Keeps it running but lets everything else go first. Your Mac feels faster; this one gets a little slower. Nothing is lost."
        case .quit:
            return "Closes it the normal way, like choosing Quit from its menu. Save your work in it first."
        case .forceQuit:
            return "Stops it immediately. Only do this if it's frozen — you may lose anything you hadn't saved."
        }
    }

    var isDestructive: Bool { self != .slowDown }

    /// Short confirmation shown after it's done, e.g. "Slowed down Chrome."
    func doneMessage(_ name: String) -> String {
        switch self {
        case .slowDown:  return "Slowed down \(name)."
        case .quit:      return "Asked \(name) to quit."
        case .forceQuit: return "Force-quit \(name)."
        }
    }
}

enum PlainLanguage {
    /// Programs that are part of macOS. We list them (so the picture is honest)
    /// but never offer to stop them — quitting these can freeze or log you out.
    static let systemCommands: Set<String> = [
        "kernel_task", "launchd", "WindowServer", "loginwindow", "Finder",
        "Dock", "SystemUIServer", "coreaudiod", "powerd", "configd", "syslogd",
        "diskarbitrationd", "mDNSResponder", "WindowManager", "controlcenter",
        "Spotlight", "mds", "mds_stores", "mdworker", "mdworker_shared",
        "corespotlightd", "trustd", "syspolicyd", "cfprefsd", "distnoted",
        "Surgebar", "surgebar",
    ]

    /// System programs → (friendly name, plain description).
    private static let systemInfo: [String: (name: String, what: String)] = [
        "Surgebar":         ("surgebar", "This is surgebar itself — the window you're looking at right now."),
        "surgebar":         ("surgebar", "This is surgebar itself — the window you're looking at right now."),
        "kernel_task":      ("macOS itself", "The core of macOS. It also spins up on purpose to keep your Mac cool — leave it be."),
        "WindowServer":     ("The screen", "Draws everything you see on the display. macOS needs it."),
        "Dock":             ("The Dock", "The bar of app icons at the edge of your screen."),
        "Finder":           ("Finder", "The macOS file browser — your desktop, folders and files."),
        "SystemUIServer":   ("The menu bar", "Runs the icons and clock at the top-right of your screen."),
        "loginwindow":      ("Login", "Handles logging in and out. macOS needs it."),
        "coreaudiod":       ("Sound", "Handles all audio in and out of your Mac."),
        "mds":              ("Spotlight search", "Building the index that lets you search your files instantly. It settles down on its own — best to just wait."),
        "mds_stores":       ("Spotlight search", "Building the search index for your files. This finishes on its own; waiting is better than stopping it."),
        "mdworker":         ("Spotlight search", "Reading files so you can search them later. It stops by itself when done."),
        "mdworker_shared":  ("Spotlight search", "Reading files so you can search them later. It stops by itself when done."),
        "photoanalysisd":   ("Photos", "Scanning your photo library to recognise people and places. It pauses when you use your Mac and finishes overnight."),
        "mediaanalysisd":   ("Photos & media", "Analysing photos and videos in the background. It finishes on its own."),
        "bird":             ("iCloud Drive", "Syncing your files with iCloud."),
        "cloudd":           ("iCloud", "Keeping your Mac in sync with iCloud."),
        "backupd":          ("Time Machine", "Backing up your Mac. Best left to finish."),
        "trustd":           ("Security", "Checking website and app security certificates. Part of macOS."),
        "syspolicyd":       ("Security", "Checking that apps are safe to open. Part of macOS."),
        "WindowManager":    ("Stage Manager", "Manages window layouts. Part of macOS."),
        "controlcenter":    ("Control Centre", "The Wi-Fi, sound and battery menu at the top of your screen."),
        "mDNSResponder":    ("Network", "Finds printers, AirPlay and shared devices on your network."),
    ]

    /// Recognisable apps → plain description. Matched loosely (the key just has to
    /// appear in the app's name), so "Google Chrome" matches "chrome".
    private static let appInfo: [(needle: String, what: String)] = [
        ("chrome",       "The web browser you use to visit websites."),
        ("safari",       "Apple's web browser."),
        ("firefox",      "A web browser."),
        ("arc",          "A web browser."),
        ("brave",        "A web browser."),
        ("edge",         "Microsoft's web browser."),
        ("slack",        "A messaging app for work chats."),
        ("discord",      "A chat and voice app."),
        ("zoom",         "A video-calling app."),
        ("teams",        "Microsoft's video and chat app."),
        ("whatsapp",     "A messaging app."),
        ("telegram",     "A messaging app."),
        ("spotify",      "A music-streaming app."),
        ("music",        "Apple Music — plays your songs."),
        ("photos",       "Your photo library."),
        ("mail",         "Your email app."),
        ("messages",     "Apple's texting app."),
        ("notion",       "A notes and documents app."),
        ("obsidian",     "A notes app."),
        ("word",         "Microsoft Word — documents."),
        ("excel",        "Microsoft Excel — spreadsheets."),
        ("powerpoint",   "Microsoft PowerPoint — slideshows."),
        ("cursor",       "A code editor for programming."),
        ("xcode",        "Apple's tool for building apps."),
        ("visual studio","A code editor for programming."),
        ("code",         "A code editor for programming."),
        ("docker",       "Runs other software in isolated containers (for developers)."),
        ("terminal",     "A window for typing commands to your Mac."),
        ("iterm",        "A window for typing commands to your Mac."),
        ("figma",        "A design app."),
        ("photoshop",    "An image-editing app."),
        ("final cut",    "A video-editing app."),
        ("premiere",     "A video-editing app."),
        ("obs",          "An app for recording and streaming your screen."),
        ("preview",      "The macOS app for viewing PDFs and images."),
        ("acrobat",      "Adobe's PDF app."),
        ("steam",        "A games app."),
    ]

    static func describe(_ p: RunningProcess) -> PlainProcess {
        if let sys = systemInfo[p.command] {
            return PlainProcess(raw: p, name: sys.name, whatItIs: sys.what, isSystem: true)
        }
        if systemCommands.contains(p.command) {
            return PlainProcess(raw: p, name: prettyFallbackName(p.command),
                                whatItIs: "Part of macOS. Best left running.", isSystem: true)
        }

        let bundle = bundleName(forExecutable: p.executablePath)
        let title = bundle ?? prettyFallbackName(p.command)
        let lower = title.lowercased()
        if let match = appInfo.first(where: { lower.contains($0.needle) }) {
            return PlainProcess(raw: p, name: title, whatItIs: match.what, isSystem: false)
        }
        let generic = bundle != nil
            ? "An app you have open."
            : "A helper program running in the background — usually part of an app you're using."
        return PlainProcess(raw: p, name: title, whatItIs: generic, isSystem: false)
    }

    // MARK: - Helpers

    /// Turn a raw unix name into something a touch more readable when we have nothing better.
    private static func prettyFallbackName(_ command: String) -> String {
        command.isEmpty ? "A background program" : command
    }

    /// Walk up an executable path to its .app bundle and read the display name.
    private static func bundleName(forExecutable path: String) -> String? {
        guard !path.isEmpty else { return nil }
        var url = URL(fileURLWithPath: path)
        while url.pathComponents.count > 1 {
            if url.pathExtension == "app" {
                let info = url.appendingPathComponent("Contents/Info.plist")
                if let dict = NSDictionary(contentsOf: info) {
                    if let n = dict["CFBundleDisplayName"] as? String, !n.isEmpty { return n }
                    if let n = dict["CFBundleName"] as? String, !n.isEmpty { return n }
                }
                return url.deletingPathExtension().lastPathComponent
            }
            url.deleteLastPathComponent()
        }
        return nil
    }
}
