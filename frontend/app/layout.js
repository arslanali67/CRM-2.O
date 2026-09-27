export const metadata = { title: "Job Outreach CRM" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", maxWidth: 640, margin: "48px auto", padding: "0 16px" }}>
        {children}
      </body>
    </html>
  );
}
