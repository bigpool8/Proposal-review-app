"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function StatusPage() {
  const params = useParams();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/jobs/${params.id}/results`);
  }, [params.id, router]);

  return null;
}
