import SwiftUI

/// System-Settings-style form for bring-your-own-key AI advice. Native `Form`
/// with grouped sections, secure key entry, and a real connection test.
struct SettingsView: View {
    @ObservedObject var settings: TriageSettings

    @State private var testing = false
    @State private var testResult: String?
    @State private var testOK = false

    var body: some View {
        Form {
            Section {
                Picker("Service", selection: $settings.provider) {
                    Text("OpenAI-compatible").tag(TriageConfig.Provider.openAI)
                    Text("Anthropic (Claude)").tag(TriageConfig.Provider.anthropic)
                }
                TextField("Endpoint", text: $settings.baseURL, prompt: Text("https://api.openai.com"))
                    .textFieldStyle(.roundedBorder)
                TextField("Model", text: $settings.model, prompt: Text("model name"))
                    .textFieldStyle(.roundedBorder)
                SecureField("Your API key", text: $settings.apiKey)
                    .textFieldStyle(.roundedBorder)
                if !settings.apiKey.isEmpty {
                    Button("Remove key") { settings.removeAPIKey() }
                        .controlSize(.small)
                }
            } header: {
                Text("AI advice")
            } footer: {
                Text("Optional. surgebar never uses anyone else's key — you bring your own. It's stored in your Mac's Keychain and only talks to the service you pick above. Works with OpenAI, Mistral, Groq, OpenRouter, or a local model (Ollama, LM Studio).")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Section {
                HStack {
                    Button {
                        runTest()
                    } label: {
                        if testing { ProgressView().controlSize(.small) }
                        else { Text("Test connection") }
                    }
                    .disabled(testing || !settings.isConfigured)

                    if let result = testResult {
                        Label(result, systemImage: testOK ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(testOK ? .green : .orange)
                            .font(.callout)
                            .lineLimit(2)
                    }
                    Spacer()
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 460, height: 380)
        .onChange(of: settings.provider) { _, newValue in applyProviderDefaults(newValue) }
    }

    private func runTest() {
        testing = true
        testResult = nil
        let config = settings.config
        Task {
            let outcome = await TriageEngine.test(config: config)
            switch outcome {
            case .success(let reply):
                testOK = true
                testResult = "Connected — the AI replied “\(reply.prefix(40))”."
            case .failure(let error):
                testOK = false
                testResult = error.errorDescription ?? "Couldn't connect."
            }
            testing = false
        }
    }

    /// When someone switches service, move the endpoint/model to that service's
    /// usual defaults — but only if they hadn't typed something custom.
    private func applyProviderDefaults(_ provider: TriageConfig.Provider) {
        let openAIDefaults = ("https://api.openai.com", "gpt-4o-mini")
        let anthropicDefaults = ("https://api.anthropic.com", "claude-haiku-4-5-20251001")
        let known = [openAIDefaults.0, anthropicDefaults.0]
        let knownModels = [openAIDefaults.1, anthropicDefaults.1]

        if settings.baseURL.isEmpty || known.contains(settings.baseURL) {
            settings.baseURL = provider == .openAI ? openAIDefaults.0 : anthropicDefaults.0
        }
        if settings.model.isEmpty || knownModels.contains(settings.model) {
            settings.model = provider == .openAI ? openAIDefaults.1 : anthropicDefaults.1
        }
    }
}
