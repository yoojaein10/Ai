"use client";

import React from "react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export default function Input({
  label,
  error,
  className = "",
  id,
  ...props
}: InputProps) {
  const inputId = id || label?.toLowerCase().replace(/\s+/g, "-");

  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="block text-sm font-medium text-txt-primary mb-1"
        >
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={`w-full px-3 py-2 border border-border rounded-lg text-sm text-txt-primary
          placeholder:text-txt-secondary bg-bg-primary
          focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent
          disabled:bg-bg-secondary disabled:cursor-not-allowed
          transition-all duration-200 ${error ? "border-cal-red focus:ring-cal-red" : ""} ${className}`}
        {...props}
      />
      {error && <p className="mt-1 text-xs text-cal-red">{error}</p>}
    </div>
  );
}
