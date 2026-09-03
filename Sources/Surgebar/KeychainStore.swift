import Foundation
import Security

/// Stores the user's own AI key in the login Keychain — never in a plist or on disk
/// in the clear. surgebar never ships or uses anyone else's key.
enum KeychainStore {
    private static let service = "com.talvinder.surgebar"
    private static let account = "ai-api-key"

    private static var base: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    /// Saves a key. An empty value is ignored rather than treated as "delete":
    /// a failed read (for example after the app is re-signed and loses access to
    /// its own Keychain item) used to write "" straight back and destroy the
    /// stored key. Removal is deliberate only — see `clearAPIKey()`.
    static func setAPIKey(_ value: String) {
        guard !value.isEmpty, let data = value.data(using: .utf8) else { return }
        SecItemDelete(base as CFDictionary)
        var add = base
        add[kSecValueData as String] = data
        SecItemAdd(add as CFDictionary, nil)
    }

    /// Explicit removal, only from the "Remove key" button in Settings.
    static func clearAPIKey() {
        SecItemDelete(base as CFDictionary)
    }

    static func apiKey() -> String {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data,
              let value = String(data: data, encoding: .utf8) else { return "" }
        return value
    }
}
