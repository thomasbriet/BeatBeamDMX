import Foundation

private var assertions = 0

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    assertions += 1
    if !condition() {
        fputs("FAIL: \(message)\n", stderr)
        exit(1)
    }
}

private func configData(slotCount: Int, marker: String) -> Data {
    let ids = (0..<slotCount).map { "fixture_\($0)" }
    let slots = Dictionary(uniqueKeysWithValues: ids.enumerated().map { index, id in
        (id, [
            "fixture": "fixture-profile-\(index)",
            "address": 1 + index * 16,
            "position_m": ["x": Double(index), "y": 2.0, "z": 3.0],
            "calibration": ["marker": marker],
        ] as [String: Any])
    })
    return try! JSONSerialization.data(withJSONObject: [
        "active_slot": ids.first ?? "",
        "slot_order": ids,
        "slots": slots,
        "marker": marker,
    ], options: [.sortedKeys])
}

private func withTemporaryDirectory(_ body: (URL) throws -> Void) rethrows {
    let root = FileManager.default.temporaryDirectory
        .appendingPathComponent("beatbeam-config-bootstrap-\(UUID().uuidString)", isDirectory: true)
    try! FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    try body(root)
}

@main
struct NativeConfigPreservationTests {
    static func main() throws {
        try withTemporaryDirectory { root in
            let authoritative = root.appendingPathComponent("authoritative.json")
            let candidate = root.appendingPathComponent("larger.json")
            let existing = configData(slotCount: 2, marker: "small-user-config")
            try existing.write(to: authoritative)
            try configData(slotCount: 8, marker: "larger-default").write(to: candidate)

            let result = try BackendConfigBootstrap.seedIfNeeded(
                authoritativeURL: authoritative, candidateURLs: [candidate]
            )
            require(result == .existingValid, "small existing config remains authoritative")
            let persisted = try Data(contentsOf: authoritative)
            require(persisted == existing, "small existing bytes are unchanged")
        }

        try withTemporaryDirectory { root in
            let authoritative = root.appendingPathComponent("authoritative.json")
            let candidate = root.appendingPathComponent("smaller.json")
            let existing = configData(slotCount: 6, marker: "large-user-config")
            try existing.write(to: authoritative)
            try configData(slotCount: 1, marker: "small-default").write(to: candidate)

            let result = try BackendConfigBootstrap.seedIfNeeded(
                authoritativeURL: authoritative, candidateURLs: [candidate]
            )
            require(result == .existingValid, "larger existing config remains authoritative")
            let persisted = try Data(contentsOf: authoritative)
            require(persisted == existing, "larger existing bytes are unchanged")
        }

        try withTemporaryDirectory { root in
            let authoritative = root.appendingPathComponent("authoritative.json")
            let zero = configData(slotCount: 0, marker: "intentional-empty")
            try zero.write(to: authoritative)

            let result = try BackendConfigBootstrap.seedIfNeeded(
                authoritativeURL: authoritative,
                candidateURLs: [root.appendingPathComponent("missing.json")]
            )
            require(result == .existingValid, "zero-fixture config is structurally valid")
            let persisted = try Data(contentsOf: authoritative)
            require(persisted == zero, "zero-fixture config is unchanged")
        }

        try withTemporaryDirectory { root in
            let authoritative = root.appendingPathComponent("support/authoritative.json")
            let corrupt = root.appendingPathComponent("corrupt.json")
            let firstValid = root.appendingPathComponent("legacy.json")
            let laterValid = root.appendingPathComponent("bundled.json")
            try Data("{ invalid".utf8).write(to: corrupt)
            let expected = configData(slotCount: 2, marker: "first-valid-source")
            try expected.write(to: firstValid)
            try configData(slotCount: 9, marker: "later-larger-source").write(to: laterValid)

            let result = try BackendConfigBootstrap.seedIfNeeded(
                authoritativeURL: authoritative,
                candidateURLs: [corrupt, firstValid, laterValid]
            )
            require(result == .seeded(firstValid), "missing config uses explicit first-valid precedence")
            let persisted = try Data(contentsOf: authoritative)
            require(persisted == expected, "initial seed preserves selected source")
        }

        try withTemporaryDirectory { root in
            let authoritative = root.appendingPathComponent("authoritative.json")
            let candidate = root.appendingPathComponent("default.json")
            let corrupt = Data("{ invalid".utf8)
            try corrupt.write(to: authoritative)
            try configData(slotCount: 4, marker: "default").write(to: candidate)

            let result = try BackendConfigBootstrap.seedIfNeeded(
                authoritativeURL: authoritative, candidateURLs: [candidate]
            )
            require(result == .existingInvalid, "corrupt existing config blocks seeding")
            let persisted = try Data(contentsOf: authoritative)
            require(persisted == corrupt, "corrupt existing config is preserved")
        }

        print("PASS: \(assertions) native config preservation assertions")
    }
}
