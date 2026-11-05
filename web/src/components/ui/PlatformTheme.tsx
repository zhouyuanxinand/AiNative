import { ConfigProvider, theme, type ThemeConfig } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';
import '../../fonts.css';

/** One theme for Ant Design controls and the platform's domain-specific surfaces. */
export const platformTheme: ThemeConfig = {
  token: {
    colorPrimary: '#236a83',
    colorPrimaryBg: '#edf4f7',
    colorPrimaryBgHover: '#e0edf2',
    colorInfo: '#236a83',
    colorInfoBg: '#edf4f7',
    colorText: '#223241',
    colorTextSecondary: '#617384',
    colorTextTertiary: '#6e8090',
    colorBgLayout: '#eff3f6',
    colorBgContainer: '#ffffff',
    colorBorder: '#c9d5df',
    colorBorderSecondary: '#dce4eb',
    fontFamily: '"RD Sans", "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif',
    fontFamilyCode: '"RD Mono", "Cascadia Code", Consolas, "RD Sans", monospace',
    fontSize: 14,
    borderRadius: 6,
    borderRadiusLG: 8,
    controlHeight: 32,
    controlHeightSM: 24,
    controlHeightLG: 40,
    motion: false,
  },
  components: {
    Button: { primaryShadow: '0 1px 2px rgb(20 38 50 / 12%)', defaultShadow: 'none', dangerShadow: 'none', fontWeight: 500 },
    Card: { headerFontSize: 16, headerHeight: 56, bodyPadding: 24 },
    Table: { headerBg: '#f4f7f9', cellPaddingBlock: 14, cellPaddingInline: 16, fontSize: 14 },
    Tabs: { horizontalItemGutter: 24, horizontalItemPadding: '12px 0', titleFontSize: 14 },
    Modal: { titleFontSize: 18, titleLineHeight: 1.5 },
    Menu: { darkItemBg: '#142632', darkSubMenuItemBg: '#142632', itemHeight: 40, itemBorderRadius: 6 },
  },
};

function PlatformTokens({ children }: { children: ReactNode }) {
  const { token: t } = theme.useToken();
  const variables: Record<string, string | number> = {
    'color-bg-page': t.colorBgLayout, 'color-bg-surface': t.colorBgContainer,
    'color-bg-subtle': '#f4f7f9', 'color-bg-hover': '#eaf0f4', 'color-bg-selected': t.colorPrimaryBg,
    'color-text-primary': t.colorText, 'color-text-secondary': t.colorTextSecondary,
    'color-text-tertiary': t.colorTextTertiary, 'color-text-inverse': t.colorTextLightSolid, 'color-text-link': t.colorLink,
    'color-border': t.colorBorderSecondary, 'color-border-strong': t.colorBorder, 'color-border-hover': t.colorPrimaryHover,
    'color-border-focus': t.colorPrimary, 'color-action': t.colorPrimary,
    'color-action-hover': t.colorPrimaryHover, 'color-action-pressed': t.colorPrimaryActive,
    'color-action-subtle': t.colorPrimaryBg, 'color-action-soft': t.colorPrimaryBg,
    'color-success': t.colorSuccessText, 'color-success-bg': t.colorSuccessBg, 'color-success-border': t.colorSuccessBorder,
    'color-warning': t.colorWarningText, 'color-warning-bg': t.colorWarningBg, 'color-warning-border': t.colorWarningBorder,
    'color-error': t.colorErrorText, 'color-error-bg': t.colorErrorBg, 'color-error-border': t.colorErrorBorder,
    'color-disabled-bg': t.colorBgContainerDisabled, 'color-disabled-text': t.colorTextDisabled, 'color-disabled-border': t.colorBorder,
    'font-family-sans': t.fontFamily, 'font-family-mono': t.fontFamilyCode,
    'font-size-body': `${t.fontSize}px`, 'font-size-control': `${t.fontSize}px`,
    'radius-sm': `${t.borderRadius}px`, 'radius-control': `${t.borderRadius}px`,
    'radius-card': `${t.borderRadiusLG}px`, 'radius-dialog': `${t.borderRadiusLG}px`,
    'shadow-raised': '0 2px 8px rgb(20 38 50 / 4%)', 'shadow-popover': t.boxShadowSecondary, 'shadow-dialog': t.boxShadow,
    'color-nav-bg': '#142632', 'color-nav-text': '#c1cfd9', 'color-nav-selected': '#294554',
    'color-nav-border': '#2b3e4a', 'color-nav-hover': '#203844', 'color-nav-accent': '#77b4c9', 'color-canvas-dot': '#cddbe4',
    'color-section-header': '#f6f8fa', 'font-size-title-lg': '24px', 'font-size-title-md': '20px',
  };
  return <><style data-platform-theme="ant-design">{`:root{${Object.entries(variables).map(([key, value]) => `--${key}:${value}`).join(';')}}`}</style>{children}</>;
}

export function PlatformTheme({ children }: { children: ReactNode }) {
  return <ConfigProvider locale={zhCN} theme={platformTheme} button={{ autoInsertSpace: false }}><PlatformTokens>{children}</PlatformTokens></ConfigProvider>;
}
