import XCTest
@testable import Surgebar

final class ElsewhereTests: XCTestCase {
    func decode(_ text: String) throws -> EWJSON { try JSONDecoder().decode(EWJSON.self, from: Data(text.utf8)) }
    func testMissingIsNotZeroAndUnknownSchemaFieldsAreAccepted() throws {
        let value = try decode(#"{"count":0,"ready":false,"extra":{"future":true}}"#)
        XCTAssertEqual(value["count"].number, 0)
        XCTAssertNil(value["missing"].number)
        XCTAssertEqual(value["missing"].text, "Unavailable")
        XCTAssertFalse(value["ready"].yes)
    }
    func testPermissionArgumentsPreserveSourceAsOneArgumentAndRequireValidTrust() throws {
        let trust = try decode(#"{"valid":true,"providers":{"fly":{}},"source":{"allowed_roots":["/tmp/project with spaces; echo nope"],"allow_private":true,"allow_uncommitted":false}}"#)
        let args = try EWPermissionDraft().arguments(path: "/tmp/config with spaces.json", trust: trust)
        XCTAssertTrue(args.contains("/tmp/project with spaces; echo nope"))
        XCTAssertTrue(args.contains("--allow-private"))
        XCTAssertTrue(args.contains("--no-allow-uncommitted"))
        XCTAssertFalse(args.contains("--execute"))
        XCTAssertThrowsError(try EWPermissionDraft().arguments(path: "/tmp/config", trust: .null))
        var invalid = EWPermissionDraft(); invalid.cost = .infinity
        XCTAssertThrowsError(try invalid.arguments(path: "/tmp/config", trust: trust))
    }
    func script(_ body: String) throws -> (URL, URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let executable = directory.appendingPathComponent("fake elsewhere")
        try Data(("#!/bin/sh\n" + body).utf8).write(to: executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        return (directory, executable)
    }
    func testArgumentArraysNeverExecuteShellText() async throws {
        let (dir, exe) = try script("printf '%s' \"$1\"\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        let argument = "$(touch SHOULD_NOT_EXIST); a b"
        let data = try await ElsewhereClient(executable: exe, directory: dir).run([argument])
        XCTAssertEqual(String(data: data, encoding: .utf8), argument)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("SHOULD_NOT_EXIST").path))
    }
    func testNonzeroErrorDoesNotExposeStderr() async throws {
        let (dir, exe) = try script("echo private-token >&2\nexit 1\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        do { _ = try await ElsewhereClient(executable: exe, directory: dir).run(["providers"]); XCTFail("Expected failure") }
        catch { XCTAssertFalse(error.localizedDescription.contains("private-token")) }
    }
    func testHungCLIIsTerminated() async throws {
        let (dir, exe) = try script("exec /bin/sleep 20\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        let start = Date()
        do { _ = try await ElsewhereClient(executable: exe, directory: dir).run(["status"], timeout: 0.2); XCTFail("Expected timeout") }
        catch { XCTAssertLessThan(Date().timeIntervalSince(start), 3) }
    }
    @MainActor func testAIAllowlistOmitsPathsCommandsAccountsAndReasons() throws {
        let model = ElsewhereModel()
        model.queue = try decode(#"{"capacity":{"memory":{"memory_level":40},"budget":{"available_mb":4096},"capacity_band":{"reason":"SECRET-REASON"}},"active_jobs":[{"command":"SECRET-COMMAND","source_path":"SECRET-PATH"}]}"#)
        model.providers = try decode(#"{"trust":{"receipt":"SECRET-RECEIPT","artifact_store":{"account":"SECRET-ACCOUNT"}}}"#)
        XCTAssertFalse(model.aiSummary.contains("SECRET"))
        XCTAssertTrue(model.aiSummary.contains("4096"))
    }
}

extension ElsewhereTests {
    func testDiagnosticNonzeroStillDecodesReadiness() async throws {
        let (dir, exe) = try script("printf '%s' '{\"checks\":[],\"ready_for_execution\":false}'\nexit 1\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        let value = try await ElsewhereClient(executable: exe, directory: dir).json(["doctor", "--json"], diagnostic: true)
        XCTAssertFalse(value["ready_for_execution"].yes)
    }
    @MainActor func testFailedRefreshRetainsSnapshotAndDirectoryChangeClearsIt() async throws {
        let (dir, exe) = try script("case \"$1\" in\nqueue) echo '{\"capacity\":{},\"active_jobs\":[]}' ;;\nproviders) echo '{\"providers\":{},\"trust\":{\"valid\":false}}' ;;\ndoctor) echo '{\"checks\":[]}' ;;\n*) echo 'elsewhere test' ;;\nesac\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        let model = ElsewhereModel(executable: exe, directory: dir, discoverOnRefresh: false)
        await model.refresh()
        XCTAssertNotNil(model.updated)
        XCTAssertNil(model.error)
        let previous = model.queue
        try Data("#!/bin/sh\nexit 2\n".utf8).write(to: exe)
        await model.refresh()
        XCTAssertNotNil(model.error)
        XCTAssertEqual(model.queue, previous)
        model.selectDirectory(dir.appendingPathComponent("other"))
        XCTAssertNil(model.updated)
        XCTAssertEqual(model.queue, .null)
    }
    @MainActor func testInheritedPermissionCannotBeEditedInProject() throws {
        let (dir, _) = try script("exit 0\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        let config = dir.appendingPathComponent("config.json")
        try Data(#"{"trust":{"approved":false,"inherit_global":true}}"#.utf8).write(to: config)
        let model = ElsewhereModel()
        model.providers = try decode(#"{"trust":{"valid":true}}"#)
        let doctor: [String: Any] = ["checks": [["name":"config", "status":"pass", "message":"configuration found at " + config.path]]]
        model.doctor = try JSONDecoder().decode(EWJSON.self, from: JSONSerialization.data(withJSONObject: doctor))
        XCTAssertNil(model.editableConfig)
    }
    func testMalformedJSONIsRejected() async throws {
        let (dir, exe) = try script("echo 'not json'\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        do { _ = try await ElsewhereClient(executable: exe, directory: dir).json(["providers"]); XCTFail("Expected malformed response") }
        catch { XCTAssertTrue(error.localizedDescription.contains("unsupported")) }
    }
}

extension ElsewhereTests {
    @MainActor func testDestinationChangeAfterReviewDoesNotApproveAnything() async throws {
        let (dir, exe) = try script("if [ \"$1\" = providers ]; then echo '{\"providers\":{\"fly\":{\"config\":{\"app\":\"changed\"}}}}'; else touch mutation-was-run; echo '{}'; fi\n")
        defer { try? FileManager.default.removeItem(at: dir) }
        let config = dir.appendingPathComponent("config.json")
        let data = Data(#"{"trust":{"approved":true}}"#.utf8)
        try data.write(to: config)
        let model = ElsewhereModel(executable: exe, directory: dir, discoverOnRefresh: false)
        model.providers = try decode(#"{"providers":{"fly":{"config":{"app":"original"}}},"trust":{"valid":true}}"#)
        model.doctor = try JSONDecoder().decode(EWJSON.self, from: JSONSerialization.data(withJSONObject: ["checks": [["name": "config", "status": "pass", "message": "configuration found at " + config.path]]]))
        XCTAssertNotNil(model.editableConfig)
        await model.perform(["trust-approve", "--path", config.path], expectedConfig: data)
        XCTAssertTrue(model.error?.contains("changed") == true)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("mutation-was-run").path))
        XCTAssertEqual(try Data(contentsOf: config), data)
    }
}
