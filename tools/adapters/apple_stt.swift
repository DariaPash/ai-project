import Foundation
import Speech

func emit(_ value: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}
let args = CommandLine.arguments
let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en_US"))
let authorized = SFSpeechRecognizer.authorizationStatus() == .authorized
if args.count < 2 || args[1] == "--probe" {
    emit(["authorized": authorized, "authorization_status": SFSpeechRecognizer.authorizationStatus().rawValue, "on_device": recognizer?.supportsOnDeviceRecognition ?? false])
} else if !authorized || recognizer?.supportsOnDeviceRecognition != true {
    emit(["status": "unavailable", "reason": "Apple Speech needs granted OS authorization and an installed on-device recognizer; no permission prompt or cloud fallback was invoked"])
} else {
    let request = SFSpeechURLRecognitionRequest(url: URL(fileURLWithPath: args[1]))
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = false
    var finished = false
    var payload: [String: Any] = ["status": "failed", "reason": "No final local recognition receipt"]
    let task = recognizer!.recognitionTask(with: request) { result, error in
        if let result = result, result.isFinal {
            payload = ["status": "ok", "segments": result.bestTranscription.segments.map { s in
                ["start_ms": Int((s.timestamp * 1000).rounded()), "end_ms": Int(((s.timestamp + s.duration) * 1000).rounded()), "text": s.substring, "confidence": Double(s.confidence)]
            }]
            finished = true
        } else if error != nil { finished = true }
    }
    let deadline = Date().addingTimeInterval(25)
    while !finished && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
    task.cancel()
    emit(payload)
}
