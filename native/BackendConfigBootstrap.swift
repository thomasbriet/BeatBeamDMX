import Foundation

enum BackendConfigBootstrap {
    enum SeedResult: Equatable {
        case existingValid
        case existingInvalid
        case seeded(URL)
        case noSeedSource
    }

    static func isStructurallyValidConfig(data: Data) -> Bool {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let slots = payload["slots"] as? [String: Any],
              let slotOrder = payload["slot_order"] as? [Any],
              slots.values.allSatisfy({ $0 is [String: Any] }),
              slotOrder.allSatisfy({ $0 is String }) else {
            return false
        }
        return true
    }

    @discardableResult
    static func seedIfNeeded(
        authoritativeURL: URL,
        candidateURLs: [URL],
        log: (String) -> Void = { _ in }
    ) throws -> SeedResult {
        let fileManager = FileManager.default

        if fileManager.fileExists(atPath: authoritativeURL.path) {
            guard let data = try? Data(contentsOf: authoritativeURL),
                  isStructurallyValidConfig(data: data) else {
                log("existing config is invalid and was preserved at \(authoritativeURL.path)")
                return .existingInvalid
            }
            return .existingValid
        }

        for candidateURL in candidateURLs where candidateURL != authoritativeURL {
            guard fileManager.fileExists(atPath: candidateURL.path),
                  let data = try? Data(contentsOf: candidateURL),
                  isStructurallyValidConfig(data: data) else {
                continue
            }
            try fileManager.createDirectory(
                at: authoritativeURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: authoritativeURL, options: .atomic)
            log("initialized config from \(candidateURL.path) at \(authoritativeURL.path)")
            return .seeded(candidateURL)
        }

        log("no valid initialization config found for \(authoritativeURL.path)")
        return .noSeedSource
    }
}
