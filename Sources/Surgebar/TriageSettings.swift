import Foundation

/// User's AI choice, remembered between launches. Provider/model/endpoint live in
/// preferences; the key lives in the Keychain. Empty by default — AI advice is
/// entirely opt-in and always uses the user's own key.
@MainActor
final class TriageSettings: ObservableObject {
    @Published var provider: TriageConfig.Provider { didSet { defaults.set(provider.rawValue, forKey: "provider") } }
    @Published var baseURL: String { didSet { defaults.set(baseURL, forKey: "baseURL") } }
    @Published var model: String { didSet { defaults.set(model, forKey: "model") } }
    // Empty writes are ignored, never persisted as a deletion — SwiftUI's
    // SecureField can write "" back transiently, which would otherwise wipe a
    // perfectly good key. Use `removeAPIKey()` to clear on purpose.
    @Published var apiKey: String { didSet { KeychainStore.setAPIKey(apiKey) } }

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard, readAPIKey: () -> String = KeychainStore.apiKey) {
        self.defaults = defaults
        provider = TriageConfig.Provider(rawValue: defaults.string(forKey: "provider") ?? "") ?? .openAI
        baseURL = defaults.string(forKey: "baseURL") ?? "https://api.openai.com"
        model = defaults.string(forKey: "model") ?? "gpt-4o-mini"
        apiKey = readAPIKey()
    }

    var config: TriageConfig {
        TriageConfig(provider: provider, baseURL: baseURL, model: model, apiKey: apiKey)
    }

    var isConfigured: Bool { config.isReady }

    /// Deliberate removal of the stored key.
    func removeAPIKey() {
        KeychainStore.clearAPIKey()
        apiKey = ""
    }
}
