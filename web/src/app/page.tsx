import Link from "next/link";
import { SiteHeader, VaderMark } from "@/components/SiteHeader";

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main className="hero">
        <div className="fade-up">
          <VaderMark size={96} className="hero-mark" />
        </div>
        <h1 className="hero-brand fade-up-delay">VADER</h1>
        <p className="hero-line fade-up-delay-2">
          Web catalog for your team. Browse and approve on the site — run inside Rhino without
          exposing source.
        </p>
        <div className="hero-ctas fade-up-delay-2">
          <Link href="/register" className="btn btn-primary">
            Request beta access
          </Link>
          <Link href="/team" className="btn btn-ghost">
            Team setup
          </Link>
        </div>
      </main>
    </>
  );
}
