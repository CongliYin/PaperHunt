"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

export function DetailBackLink() {
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("returnTo") || "/";
  const href = returnTo.startsWith("/") ? returnTo : "/";

  return (
    <Link className="back" href={href}>
      Back to Paper Hunt
    </Link>
  );
}
