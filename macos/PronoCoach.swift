import AppKit
import SwiftUI
import WebKit

struct RunResult { let status: Int32; let output: String }
func run(_ path: String, _ args: [String], at: URL? = nil) throws -> RunResult {
    let p = Process(); p.executableURL = URL(fileURLWithPath: path); p.arguments = args; p.currentDirectoryURL = at
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin").path + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    p.environment = env
    let pipe = Pipe(); p.standardOutput = pipe; p.standardError = pipe
    try p.run(); let data = pipe.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
    return RunResult(status: p.terminationStatus, output: String(data: data, encoding: .utf8) ?? "")
}
func shellQuote(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }

@MainActor final class CoachModel: ObservableObject {
    @Published var ready = false
    @Published var busy = false
    @Published var status = "Préparez le coach, puis ouvrez le dashboard ou une conversation."
    @Published var pageURL: URL?
    @Published var showSetup = true
    @Published var workspace = UserDefaults.standard.string(forKey: "workspace") ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/AI Prono Coach").path
    private var server: Process?
    private var engine: URL?
    private let port = 8877
    func chooseWorkspace() {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        if panel.runModal() == .OK, let url = panel.url { workspace = url.path }
    }
    func prepare() {
        guard !busy else { return }; busy = true; status = "Préparation du moteur et des agents…"
        let dataURL = URL(fileURLWithPath: workspace)
        Task {
            do {
                let resources = Bundle.main.resourceURL!
                let build = Bundle.main.object(forInfoDictionaryKey: "PronoEngineBuild") as? String ?? "local"
                let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/AI Prono Coach")
                let engineURL = support.appendingPathComponent("engine-" + build.prefix(12))
                let result = try await Task.detached(priority: .userInitiated) { () -> RunResult in
                    try FileManager.default.createDirectory(at: engineURL, withIntermediateDirectories: true)
                    if !FileManager.default.fileExists(atPath: engineURL.appendingPathComponent("scripts/install.py").path) {
                        let unpack = try run("/usr/bin/tar", ["-xzf", resources.appendingPathComponent("engine.tar.gz").path, "-C", engineURL.path])
                        if unpack.status != 0 { return unpack }
                    }
                    let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
                    for python in candidates where FileManager.default.isExecutableFile(atPath: python) {
                        let version = try run(python, ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"])
                        if version.status == 0 {
                            return try run(python, [engineURL.appendingPathComponent("scripts/install.py").path, "--workspace", dataURL.path, "--ide", "claude", "--mcp"], at: engineURL)
                        }
                    }
                    return RunResult(status: 1, output: "Python 3.11 ou plus récent est requis. Installez Python depuis python.org, puis réessayez.")
                }.value
                guard result.status == 0 else { throw NSError(domain: "Prono", code: 1, userInfo: [NSLocalizedDescriptionKey: result.output]) }
                engine = engineURL; UserDefaults.standard.set(workspace, forKey: "workspace")
                try startServer(); ready = true; showSetup = false; status = "Coach prêt · données dans " + workspace
            } catch { status = error.localizedDescription }
            busy = false
        }
    }
    private func startServer() throws {
        guard let engine = engine else { return }
        if let server = server, server.isRunning { return }
        let p = Process(); p.executableURL = engine.appendingPathComponent(".venv/bin/python")
        p.arguments = ["-m", "prono.cli", "--workspace", workspace, "ui", "--port", String(port)]
        p.currentDirectoryURL = URL(fileURLWithPath: workspace)
        let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/AI Prono Coach/dashboard.log")
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        let log = try FileHandle(forWritingTo: logURL); try log.seekToEnd()
        p.standardOutput = log; p.standardError = log; try p.run(); server = p
        Task {
            for _ in 0..<50 {
                try? await Task.sleep(nanoseconds: 200_000_000)
                guard p.isRunning else { status = "Le dashboard n’a pas démarré. Le port 8877 est peut-être occupé."; return }
                if let url = URL(string: "http://127.0.0.1:\(port)/api/summary"), let (_, response) = try? await URLSession.shared.data(from: url), (response as? HTTPURLResponse)?.statusCode == 200 {
                    pageURL = URL(string: "http://127.0.0.1:\(port)/"); return
                }
            }
            status = "Le dashboard tarde à démarrer. Consultez le diagnostic dans le dossier de l’app."
        }
    }
    func navigate(_ path: String) { pageURL = URL(string: "http://127.0.0.1:\(port)" + path) }
    func openData() { NSWorkspace.shared.open(URL(fileURLWithPath: workspace)) }
    func claude() {
        guard let engine = engine else { return }
        let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/AI Prono Coach")
        let script = support.appendingPathComponent("Parler-au-coach.command")
        let text = "#!/bin/zsh\nexport PATH=\"$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\"\ncd " + shellQuote(workspace) + " || exit 1\nif command -v claude >/dev/null 2>&1; then exec claude; else printf '%s\\n' 'Claude Code est absent. Installez-le depuis https://code.claude.com/docs/en/setup puis réessayez.'; read; fi\n"
        do { try text.write(to: script, atomically: true, encoding: .utf8); try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path); NSWorkspace.shared.open(script); status = "Claude Code ouvert dans le dossier du coach." } catch { status = error.localizedDescription }
        _ = engine
    }
    func importData() {
        guard let engine = engine, !busy else { return }; busy = true; status = "Import des championnats et des trois coupes d’Europe…"
        let root = URL(fileURLWithPath: workspace)
        let python = engine.appendingPathComponent(".venv/bin/python").path
        Task {
            do {
                let result = try await Task.detached(priority: .userInitiated) {
                    try run(python, ["-m", "prono.cli", "--workspace", root.path, "sync-leagues", "--markets"], at: root)
                }.value
                if result.status == 0 {
                    let facts = try JSONSerialization.jsonObject(with: Data(result.output.utf8)) as? [String: Any]
                    let leagues = facts?["leagues"] as? [String: [String: Any]] ?? [:]
                    let failures = leagues.values.filter { ($0["status"] as? String) == "error" }.count
                    status = "Collecte terminée · \(failures) import(s) en échec. Voir Couverture & sources."
                    navigate("/?tab=pronos")
                } else { status = result.output }
            } catch { status = error.localizedDescription }
            busy = false
        }
    }
    func stop() { server?.terminate(); server = nil }
}

struct CoachWebView: NSViewRepresentable {
    let url: URL
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context: Context) -> WKWebView {
        let web = WKWebView(); web.navigationDelegate = context.coordinator; web.load(URLRequest(url: url)); return web
    }
    func updateNSView(_ web: WKWebView, context: Context) { if context.coordinator.lastURL != url { context.coordinator.lastURL = url; web.load(URLRequest(url: url)) } }
    class Coordinator: NSObject, WKNavigationDelegate {
        var lastURL: URL?
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            if url.host == "127.0.0.1" && url.port == 8877 { decisionHandler(.allow) }
            else { if url.scheme == "https" || url.scheme == "http" { NSWorkspace.shared.open(url) }; decisionHandler(.cancel) }
        }
    }
}

struct RootView: View {
    @StateObject var model = CoachModel()
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Label("AI Prono Coach", systemImage: "soccerball").font(.headline)
                Spacer()
                if model.ready {
                    Button("Pronos") { model.navigate("/") }
                    Button("Suivi") { model.navigate("/?tab=tracking") }
                    Button("Coach") { model.navigate("/chat") }
                    Menu("Outils") {
                        Button("Claude Code") { model.claude() }
                        Button("Mes données") { model.openData() }
                        Button("Données et sources") { model.navigate("/?tab=coverage") }
                    }
                }
            }.padding(16)
            Divider()
            if model.showSetup {
                VStack(alignment: .leading, spacing: 22) {
                    Text("Votre coach football, sur votre Mac.").font(.largeTitle.bold())
                    Text("Dashboard, pronos en fictif et chat intégré : Ollama en local ou Claude pour discuter et rechercher des actualités. Accès à Claude Code pour les spécialistes.").foregroundStyle(.secondary)
                    Text("Dossier de vos données").font(.headline)
                    HStack { TextField("Dossier", text: $model.workspace); Button("Choisir…") { model.chooseWorkspace() } }
                    Text("Le moteur prépare un environnement Python privé et l’intégration Claude. La première préparation télécharge le SDK MCP ; les données sportives seront importées à votre demande.").font(.callout).foregroundStyle(.secondary)
                    Button(model.busy ? "Préparation…" : "Préparer mon coach") { model.prepare() }.buttonStyle(.borderedProminent).disabled(model.busy)
                    Text("Python 3.11+ et votre assistant restent nécessaires. Claude Code et Ollama utilisent leurs installations et connexions habituelles.").font(.caption).foregroundStyle(.secondary)
                }.padding(40).frame(maxWidth: 800)
                Spacer()
            } else if let url = model.pageURL { CoachWebView(url: url) }
            else { ProgressView("Démarrage du dashboard…").frame(maxWidth: .infinity, maxHeight: .infinity) }
            Divider()
            HStack {
                if model.busy { ProgressView().controlSize(.small) }
                Text(model.status).font(.caption).lineLimit(3).textSelection(.enabled)
                Spacer()
                if model.ready { Button("Actualiser les championnats et coupes d’Europe") { model.importData() }.disabled(model.busy) }
            }.padding(12)
        }.frame(minWidth: 980, minHeight: 700).onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in model.stop() }
    }
}
@main struct AIPronoCoachApp: App {
    var body: some Scene { WindowGroup { RootView() }.commands { CommandGroup(replacing: .newItem) {} } }
}
