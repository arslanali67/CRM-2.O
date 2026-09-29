import Script from "next/script";
import "./globals.css";
import Shell from "./topbar";
import { DialogProvider, ToastProvider } from "./ui";

export const metadata = { title: "Job Outreach CRM" };

// Applies the saved theme before first paint (no light flash in dark mode).
const THEME = `try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><Script id="theme" strategy="beforeInteractive">{THEME}</Script></head>
      <body>
        <ToastProvider>
          <DialogProvider>
            <Shell>{children}</Shell>
          </DialogProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
