import { createRoot } from "react-dom/client";
import App from "./App";
import { AppProviders, AuthProvider } from "./state";
import "./styles.css";

try {
  const theme = localStorage.getItem("or-theme");
  if (theme) document.documentElement.dataset.theme = theme;
} catch { /* storage unavailable */ }

createRoot(document.getElementById("root")!).render(
  <AuthProvider>
    <AppProviders>
      <App />
    </AppProviders>
  </AuthProvider>,
);
