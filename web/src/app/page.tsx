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
          Ready-to-use Rhino Python scripts — categorized, synced, and run only through Vader.
        </p>
        <div className="hero-ctas fade-up-delay-2">
          <Link href="/register" className="btn btn-primary">
            Request beta access
          </Link>
          <Link href="/login" className="btn btn-ghost">
            Sign in
          </Link>
        </div>
      </main>
    </>
  );
}
