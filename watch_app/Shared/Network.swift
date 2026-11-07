// Accès au Pi, partagé par l'app et la complication « Prochain train » (Trains/).
import Foundation

/// Session vers le Pi en **Wi-Fi seul**. Près de l'iPhone, watchOS fait passer le
/// trafic par son relais Bluetooth, qui ne joint JAMAIS le réseau local (délai
/// dépassé). URLSession ne permet pas de choisir le Wi-Fi, mais refuser les réseaux
/// « coûteux »/« restreints » écarte ce relais (constaté sur la montre, non
/// documenté par Apple) : la montre passe alors par son propre Wi-Fi.
func wifiSession(_ config: URLSessionConfiguration, timeout: TimeInterval) -> URLSession {
    config.timeoutIntervalForRequest = timeout
    config.allowsExpensiveNetworkAccess = false
    config.allowsConstrainedNetworkAccess = false
    config.allowsCellularAccess = false
    return URLSession(configuration: config)
}

/// Requête vers le Pi, avec le jeton.
func apiRequest(_ path: String) -> URLRequest {
    var req = URLRequest(url: URL(string: Secrets.baseURL + path)!)
    req.setValue("Bearer \(Secrets.token)", forHTTPHeaderField: "Authorization")
    return req
}
