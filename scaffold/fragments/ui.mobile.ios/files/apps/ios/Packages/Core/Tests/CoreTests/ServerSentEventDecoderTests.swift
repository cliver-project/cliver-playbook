import XCTest
@testable import Core

final class ServerSentEventDecoderTests: XCTestCase {
    func testBlankLineCompletesOneFrame() {
        var decoder = ServerSentEventDecoder()

        XCTAssertNil(decoder.consume(line: "id: 0"))
        XCTAssertNil(decoder.consume(line: "event: run.started"))
        XCTAssertNil(decoder.consume(line: #"data: {"type":"run.started"}"#))

        XCTAssertEqual(
            decoder.consume(line: ""),
            ServerSentEvent(
                id: "0",
                event: "run.started",
                data: #"{"type":"run.started"}"#
            )
        )
    }

    func testKeepsAdjacentFramesSeparate() {
        var decoder = ServerSentEventDecoder()

        _ = decoder.consume(line: "id: 0")
        _ = decoder.consume(line: "data: first")
        let first = decoder.consume(line: "")
        _ = decoder.consume(line: "id: 1")
        _ = decoder.consume(line: "data: second")
        let second = decoder.consume(line: "")

        XCTAssertEqual(first?.data, "first")
        XCTAssertEqual(first?.id, "0")
        XCTAssertEqual(second?.data, "second")
        XCTAssertEqual(second?.id, "1")
    }

    func testJoinsMultilineDataAndStripsOneOptionalSpace() {
        var decoder = ServerSentEventDecoder()

        _ = decoder.consume(line: "data: first line")
        _ = decoder.consume(line: "data: second line")

        XCTAssertEqual(
            decoder.consume(line: ""),
            ServerSentEvent(id: nil, event: nil, data: "first line\nsecond line")
        )
    }

    func testIgnoresCommentsAndUnknownFields() {
        var decoder = ServerSentEventDecoder()

        XCTAssertNil(decoder.consume(line: ": keepalive"))
        XCTAssertNil(decoder.consume(line: "retry: 1000"))
        XCTAssertNil(decoder.consume(line: "data: kept"))

        XCTAssertEqual(decoder.consume(line: "")?.data, "kept")
    }

    func testFinishFlushesAFrameWithoutATrailingBlankLine() {
        var decoder = ServerSentEventDecoder()

        _ = decoder.consume(line: "data: last")

        XCTAssertEqual(
            decoder.finish(),
            ServerSentEvent(id: nil, event: nil, data: "last")
        )
    }
}
