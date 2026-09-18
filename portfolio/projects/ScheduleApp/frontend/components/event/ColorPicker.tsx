"use client";

import React from "react";
import { CAL_COLORS } from "@/lib/types";

interface ColorPickerProps {
  selectedColor: string;
  onChange: (color: string) => void;
}

export default function ColorPicker({ selectedColor, onChange }: ColorPickerProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-txt-primary mb-2">
        색상
      </label>
      <div className="flex gap-2 flex-wrap">
        {CAL_COLORS.map((c) => (
          <button
            key={c.value}
            type="button"
            onClick={() => onChange(c.value)}
            className={`w-8 h-8 rounded-full transition-all duration-200 ${
              selectedColor === c.value
                ? "ring-2 ring-offset-2 scale-110"
                : "hover:scale-110"
            }`}
            style={{
              backgroundColor: c.value,
              "--tw-ring-color": c.value,
            } as React.CSSProperties}
            title={c.name}
          />
        ))}
      </div>
    </div>
  );
}
