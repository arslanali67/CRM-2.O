import TopBar from "./topbar";

export const metadata = { title: "Job Outreach CRM" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", maxWidth: 1000, margin: "24px auto", padding: "0 16px" }}>
        <TopBar />
        {children}
      </body>
    </html>
  );
}
