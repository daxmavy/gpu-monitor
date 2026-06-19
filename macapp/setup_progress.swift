// Tiny first-launch progress window, driven over stdin by the app's launcher
// script (which runs BEFORE Python exists, so this can't be Python/PyObjC).
//
// Reads lines on stdin:
//   STATUS <text>   update the task label
//   PROGRESS <0-100> determinate bar at that value
//   PULSE           indeterminate (animated) bar — for unknown-length steps
//   DONE            fill + quit
// Quits on DONE, on stdin EOF, on SIGTERM (the app kills it when its real window
// appears), or after a 5-minute safety timeout.
import AppKit

final class Controller: NSObject, NSApplicationDelegate {
    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 156),
                          styleMask: [.titled, .fullSizeContentView],
                          backing: .buffered, defer: false)
    let bar = NSProgressIndicator()
    let status = NSTextField(labelWithString: "Starting…")

    func applicationDidFinishLaunching(_ note: Notification) {
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
        window.level = .floating
        window.center()

        let v = window.contentView!

        let title = NSTextField(labelWithString: "GPU Monitor")
        title.font = .systemFont(ofSize: 18, weight: .semibold)
        title.alignment = .center
        title.frame = NSRect(x: 20, y: 104, width: 360, height: 26)
        title.autoresizingMask = [.width]

        let sub = NSTextField(labelWithString: "Setting up on first launch — about a minute.")
        sub.font = .systemFont(ofSize: 12)
        sub.textColor = .secondaryLabelColor
        sub.alignment = .center
        sub.frame = NSRect(x: 20, y: 82, width: 360, height: 18)
        sub.autoresizingMask = [.width]

        bar.minValue = 0; bar.maxValue = 100; bar.isIndeterminate = false
        bar.doubleValue = 2
        bar.frame = NSRect(x: 28, y: 52, width: 344, height: 12)
        bar.autoresizingMask = [.width]

        status.font = .systemFont(ofSize: 12)
        status.textColor = .secondaryLabelColor
        status.alignment = .center
        status.frame = NSRect(x: 20, y: 24, width: 360, height: 18)
        status.autoresizingMask = [.width]

        v.addSubview(title); v.addSubview(sub); v.addSubview(bar); v.addSubview(status)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        Thread.detachNewThread { self.readLoop() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 300) { NSApp.terminate(nil) }
    }

    func readLoop() {
        while let line = readLine(strippingNewline: true) {
            let parts = line.split(separator: " ", maxSplits: 1).map(String.init)
            let cmd = parts.first ?? ""
            let arg = parts.count > 1 ? parts[1] : ""
            DispatchQueue.main.async { self.apply(cmd, arg) }
        }
        DispatchQueue.main.async { NSApp.terminate(nil) }   // stdin closed
    }

    func apply(_ cmd: String, _ arg: String) {
        switch cmd {
        case "STATUS":
            status.stringValue = arg
        case "PROGRESS":
            bar.stopAnimation(nil); bar.isIndeterminate = false
            if let n = Double(arg) { bar.doubleValue = n }
        case "PULSE":
            bar.isIndeterminate = true; bar.startAnimation(nil)
        case "DONE":
            bar.stopAnimation(nil); bar.isIndeterminate = false; bar.doubleValue = 100
            NSApp.terminate(nil)
        default:
            break
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let c = Controller()
app.delegate = c
app.run()
