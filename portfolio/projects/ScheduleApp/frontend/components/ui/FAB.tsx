"use client";

import React from "react";

interface FABProps {
  onClick: () => void;
}

export default function FAB({ onClick }: FABProps) {
  return (
    <button
      onClick={onClick}
      className="fixed bottom-20 right-6 md:bottom-8 md:right-8 z-40
        w-14 h-14 rounded-full bg-accent text-accent-contrast shadow-lg
        flex items-center justify-center
        hover:brightness-110 active:scale-95
        transition-all duration-200"
      aria-label="Add event"
    >
      <svg
        className="w-7 h-7"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2.5}
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
      </svg>
    </button>
  );
}
