import "./globals.css";

export const metadata = {
  title: "ParkPulse AI",
  description: "Multi-agent operations copilot for amusement park disruption response",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
