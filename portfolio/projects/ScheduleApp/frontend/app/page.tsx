"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

function Redirector() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const empno = searchParams.get("empno");

  useEffect(() => {
    const query = empno ? `?empno=${empno}` : "";
    router.replace(`/calendar${query}`);
  }, [router, empno]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="animate-pulse text-txt-secondary">불러오는 중...</div>
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen">
          <div className="animate-pulse text-txt-secondary">불러오는 중...</div>
        </div>
      }
    >
      <Redirector />
    </Suspense>
  );
}
