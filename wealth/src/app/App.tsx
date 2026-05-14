import { WealthRouter } from "./routes/WealthRouter";
import { AuthProvider } from "../features/auth/model/AuthProvider";

export function App() {
  return (
    <AuthProvider>
      <WealthRouter />
    </AuthProvider>
  );
}
