"use client";

import React from "react";
import { EVENT_EMOJIS, EMOJI_MAP } from "@/lib/types";

interface EmojiPickerProps {
  selectedEmoji: string;
  onChange: (emoji: string) => void;
}

export default function EmojiPicker({ selectedEmoji, onChange }: EmojiPickerProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-txt-primary mb-2">
        Icon
      </label>
      <div className="flex gap-2 flex-wrap">
        {EVENT_EMOJIS.map((key) => {
          if (key === "") return null;
          const display = EMOJI_MAP[key] || key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onChange(selectedEmoji === key ? "" : key)}
              className={`w-10 h-10 rounded-lg flex items-center justify-center text-xl transition-all duration-200 ${
                selectedEmoji === key
                  ? "bg-accent/10 ring-2 ring-accent"
                  : "bg-bg-secondary hover:bg-bg-secondary"
              }`}
              title={key}
            >
              {display}
            </button>
          );
        })}
      </div>
    </div>
  );
}
