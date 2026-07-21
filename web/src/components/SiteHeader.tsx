import Image from "next/image";
import Link from "next/link";

export function VaderMark({
  size = 48,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <Image
      src="/brand/vader-mark.svg"
      alt="Vader"
      width={size}
      height={size}
      className={className}
      priority
    />
  );
}

export function SiteHeader({
  email,
  isAdmin,
}: {
  email?: string | null;
  isAdmin?: boolean;
}) {
  return (
    <header className="site-header">
      <Link href={email ? "/catalog" : "/"} className="brand-lockup">
        <VaderMark size={28} />
        <span className="brand-word">VADER</span>
      </Link>
      <nav className="site-nav">
        {email ? (
          <>
            <Link href="/catalog">Catalog</Link>
            <Link href="/team">Team</Link>
            <Link href="/feedback">Feedback</Link>
            {isAdmin && <Link href="/admin">Admin</Link>}
            <span className="nav-email">{email}</span>
            <Link href="/api/auth/signout" className="nav-muted">
              Sign out
            </Link>
          </>
        ) : (
          <>
            <Link href="/login">Sign in</Link>
            <Link href="/team">Team setup</Link>
            <Link href="/register" className="btn-nav">
              Request access
            </Link>
          </>
        )}
      </nav>
    </header>
  );
}
