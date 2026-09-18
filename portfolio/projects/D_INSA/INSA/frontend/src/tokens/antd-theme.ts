import type { ThemeConfig } from "antd";

/*
 * Hex equivalents of tokens.css OKLCH primitives.
 * AntD's theme token system does not parse oklch(), so these must be kept in sync.
 * When you change a color in tokens.css, update the corresponding HEX here.
 */

const PRIMARY = "#1a1a2e";
const PRIMARY_HOVER = "#272743";
const PRIMARY_ACTIVE = "#0f0f1e";

const ACCENT_WARM = "#d59749";

const SUCCESS = "#4b9e6a";
const WARNING = ACCENT_WARM;
const DANGER = "#c65a3f";
const INFO = "#3a6aa6";

const SURFACE_CANVAS = "#fbfafa";
const SURFACE_RAISED = "#ffffff";
const SURFACE_SUNKEN = "#f6f5f3";

const TEXT_PRIMARY = "#2b2c36";
const TEXT_SECONDARY = "#676a7a";
const TEXT_TERTIARY = "#94949f";

const BORDER_DEFAULT = "#e6e6ea";
const BORDER_SUBTLE = "#ededf0";

const FONT_STACK =
  '"Wanted Sans Variable","Wanted Sans",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Segoe UI","Helvetica Neue",Arial,sans-serif';

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: PRIMARY,
    colorPrimaryHover: PRIMARY_HOVER,
    colorPrimaryActive: PRIMARY_ACTIVE,
    colorLink: PRIMARY,
    colorLinkHover: PRIMARY_HOVER,
    colorInfo: INFO,
    colorSuccess: SUCCESS,
    colorWarning: WARNING,
    colorError: DANGER,

    colorText: TEXT_PRIMARY,
    colorTextSecondary: TEXT_SECONDARY,
    colorTextTertiary: TEXT_TERTIARY,
    colorTextDescription: TEXT_SECONDARY,

    colorBgBase: SURFACE_CANVAS,
    colorBgContainer: SURFACE_RAISED,
    colorBgLayout: SURFACE_CANVAS,
    colorBgElevated: SURFACE_RAISED,

    colorBorder: BORDER_DEFAULT,
    colorBorderSecondary: BORDER_SUBTLE,

    fontFamily: FONT_STACK,
    fontSize: 14,
    fontSizeSM: 13,
    fontSizeLG: 16,
    fontSizeHeading1: 24,
    fontSizeHeading2: 20,
    fontSizeHeading3: 16,
    fontSizeHeading4: 14,
    lineHeight: 1.5,

    borderRadius: 5,
    borderRadiusLG: 7,
    borderRadiusSM: 3,
    borderRadiusXS: 2,

    controlHeight: 32,
    controlHeightSM: 28,
    controlHeightLG: 40,

    motionDurationFast: "120ms",
    motionDurationMid: "200ms",
    motionDurationSlow: "320ms",

    wireframe: false,
  },
  components: {
    Layout: {
      headerBg: PRIMARY,
      headerHeight: 48,
      headerPadding: "0 20px",
      headerColor: "#ffffff",
      siderBg: SURFACE_SUNKEN,
      bodyBg: SURFACE_CANVAS,
    },
    Menu: {
      itemBg: SURFACE_SUNKEN,
      subMenuItemBg: "transparent",
      itemSelectedBg: "rgba(26, 26, 46, 0.06)",
      itemSelectedColor: PRIMARY,
      itemHoverBg: "rgba(26, 26, 46, 0.035)",
      itemHoverColor: PRIMARY,
      itemColor: TEXT_PRIMARY,
      itemHeight: 32,
      itemMarginInline: 8,
      itemMarginBlock: 2,
      itemPaddingInline: 12,
      groupTitleColor: TEXT_TERTIARY,
      groupTitleFontSize: 11,
      iconSize: 14,
      activeBarWidth: 0,
      activeBarHeight: 0,
      activeBarBorderWidth: 0,
    },
    Button: {
      primaryShadow: "none",
      defaultShadow: "none",
      dangerShadow: "none",
      fontWeight: 500,
      defaultBorderColor: BORDER_DEFAULT,
      defaultBg: SURFACE_RAISED,
    },
    Input: {
      activeShadow: "none",
      hoverBorderColor: PRIMARY,
      activeBorderColor: PRIMARY,
      colorBgContainer: SURFACE_RAISED,
    },
    Select: {
      activeBorderColor: PRIMARY,
      hoverBorderColor: PRIMARY,
      optionSelectedBg: "rgba(26, 26, 46, 0.06)",
      optionSelectedColor: PRIMARY,
    },
    Table: {
      headerBg: SURFACE_SUNKEN,
      headerColor: TEXT_SECONDARY,
      headerSplitColor: "transparent",
      rowHoverBg: "rgba(26, 26, 46, 0.03)",
      borderColor: BORDER_SUBTLE,
      cellPaddingBlock: 8,
      cellPaddingBlockSM: 6,
      cellPaddingInline: 12,
      fontSize: 13,
    },
    Tabs: {
      inkBarColor: ACCENT_WARM,
      itemSelectedColor: PRIMARY,
      itemHoverColor: PRIMARY,
      itemColor: TEXT_SECONDARY,
      titleFontSize: 14,
      horizontalItemPadding: "10px 12px",
      horizontalMargin: "0 0 16px 0",
    },
    Badge: {
      dotSize: 6,
    },
    Alert: {
      defaultPadding: "8px 12px",
      colorInfoBg: "rgba(26, 26, 46, 0.04)",
      colorInfoBorder: "transparent",
      colorWarningBg: "rgba(213, 151, 73, 0.08)",
      colorWarningBorder: "transparent",
      colorErrorBg: "rgba(198, 90, 63, 0.06)",
      colorErrorBorder: "transparent",
      colorSuccessBg: "rgba(75, 158, 106, 0.06)",
      colorSuccessBorder: "transparent",
    },
    Card: {
      headerBg: "transparent",
      paddingLG: 20,
      headerFontSize: 16,
      headerHeight: 48,
    },
    Modal: {
      titleFontSize: 16,
      headerBg: SURFACE_RAISED,
    },
    Popover: {
      titleMinWidth: 0,
    },
    Tag: {
      defaultBg: SURFACE_SUNKEN,
      defaultColor: TEXT_PRIMARY,
    },
    Divider: {
      colorSplit: BORDER_SUBTLE,
    },
  },
};

export const brandColors = {
  primary: PRIMARY,
  primaryHover: PRIMARY_HOVER,
  accent: ACCENT_WARM,
  surfaceCanvas: SURFACE_CANVAS,
  surfaceRaised: SURFACE_RAISED,
  surfaceSunken: SURFACE_SUNKEN,
  textPrimary: TEXT_PRIMARY,
  textSecondary: TEXT_SECONDARY,
  textTertiary: TEXT_TERTIARY,
  borderDefault: BORDER_DEFAULT,
  borderSubtle: BORDER_SUBTLE,
} as const;
