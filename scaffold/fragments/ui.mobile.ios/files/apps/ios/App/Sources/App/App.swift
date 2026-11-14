import Core
import SwiftUI

@main
struct MainApp: App {
    @State private var authStore = AuthStore()
    private let components = AppComponents.reference

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(authStore)
                .environment(\.appComponents, components)
                .tint(DesignSystem.accent)
        }
    }
}
