import Link from "next/link";

const sections = [
  { href: "/", label: "每日论文", icon: "issue" },
  { href: "/conferences", label: "顶会论文", icon: "volumes" },
] as const;

export function LibraryNav({ current }: { current: "/" | "/conferences" }) {
  return (
    <nav className="library-switch" aria-label="论文栏目">
      {sections.map(({ href, label, icon }) => (
        <Link key={href} href={href} aria-current={current === href ? "page" : undefined}>
          <span className={`section-icon section-icon--${icon}`} aria-hidden="true" />
          {label}
        </Link>
      ))}
    </nav>
  );
}
