import Foundation

func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fputs("FAIL: \(message)\n", stderr); exit(1) }
}

@main
struct RemoteTransportFailoverContractTests {
    static func main() {
        var gate = RemoteTransportGenerationGate()
        let originalLAN = gate.restartLAN()
        require(gate.acceptsLAN(originalLAN, usbIsActive: false), "initial LAN session accepted")

        gate.invalidateLAN() // USB becomes command/state active.
        require(!gate.acceptsLAN(originalLAN, usbIsActive: true), "USB supersedes old LAN callback")

        let fallbackLAN = gate.restartLAN() // USB session lost → fresh LAN lifecycle.
        require(gate.acceptsLAN(fallbackLAN, usbIsActive: false), "fresh LAN session accepted after USB loss")
        require(!gate.acceptsLAN(originalLAN, usbIsActive: false), "pre-USB LAN callback remains stale")

        gate.invalidateLAN() // USB returns.
        require(!gate.acceptsLAN(fallbackLAN, usbIsActive: true), "USB reacquire supersedes fallback LAN")
    }
}
