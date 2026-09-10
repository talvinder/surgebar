import XCTest
@testable import Surgebar

final class ElsewhereActivityTests: XCTestCase {
    func json(_ text: String) throws -> EWJSON { try JSONDecoder().decode(EWJSON.self, from: Data(text.utf8)) }
    func testCleanedDoesNotTreatSubmissionSuccessAsWorkSuccess() throws {
        let activity = EWActivity(job: try json(#"{"state":"cleaned","provider":"fly","returncode":0}"#))
        XCTAssertEqual(activity.title, "Resources removed")
        XCTAssertTrue(activity.explanation.contains("does not include"))
        XCTAssertFalse(activity.explanation.contains("successfully"))
    }
    func testSucceededDescribesExecutionSeparatelyFromCleanup() throws {
        let remote = EWActivity(job: try json(#"{"state":"succeeded","provider":"fly"}"#))
        XCTAssertEqual(remote.title, "Work completed")
        XCTAssertTrue(remote.explanation.contains("separate step"))
        let local = EWActivity(job: try json(#"{"state":"succeeded","provider":"local"}"#))
        XCTAssertTrue(local.explanation.contains("on this Mac"))
    }
    func testTimestampUsesCompletionThenStartThenQueuedAndNeverEpochFallback() throws {
        let done = EWActivity(job: try json(#"{"completed_at":300,"started_at":200,"created_at":100}"#))
        XCTAssertEqual(done.timestamp?.label, "Finished")
        XCTAssertEqual(done.timestamp?.date, Date(timeIntervalSince1970: 300))
        XCTAssertEqual(EWActivity(job: try json(#"{"completed_at":null,"started_at":200}"#)).timestamp?.label, "Started")
        XCTAssertEqual(EWActivity(job: try json(#"{"created_at":100}"#)).timestamp?.label, "Queued")
        XCTAssertEqual(EWActivity(job: try json(#"{"created_at":0}"#)).timestampText, "Time not recorded")
    }
    func testFailureExplainsKnownDiagnosticWithoutCopyingPathsOrSecrets() {
        let message = EWActivity.failureExplanation("error opening /secret/project/ModuleCache: Operation not permitted; token=PRIVATE")
        XCTAssertTrue(message.contains("compiler cache"))
        XCTAssertFalse(message.contains("/secret"))
        XCTAssertFalse(message.contains("PRIVATE"))
        XCTAssertTrue(EWActivity.failureExplanation("job failed").contains("No specific cause"))
    }
    func testBooleanDraftChangesBecomeExplicitCLIFlags() throws {
        let trust = try json(#"{"valid":true,"providers":{"fly":{}},"source":{"allowed_roots":["/tmp/example"],"allow_private":true,"allow_uncommitted":false}}"#)
        var draft = EWPermissionDraft()
        draft.allowPrivate = false
        draft.allowUncommitted = true
        let args = try draft.arguments(path: "/tmp/config", trust: trust)
        XCTAssertTrue(args.contains("--no-allow-private"))
        XCTAssertTrue(args.contains("--allow-uncommitted"))
        XCTAssertFalse(args.contains("--allow-private"))
        XCTAssertFalse(args.contains("--execute"))
    }
    @MainActor func testRecentActivitySortsByCompletionInsteadOfSubmission() throws {
        let model = ElsewhereModel()
        model.queue = try json(#"{"history":[{"id":"earlier","created_at":200,"completed_at":300},{"id":"later","created_at":100,"completed_at":400}]}"#)
        XCTAssertEqual(model.recentJobs.first?["id"].string, "later")
    }
}
