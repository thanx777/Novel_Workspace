import { useApp } from "../../context/AppContext"
import { AccessibleButton } from "../common/AccessibleButton"

export default function ChapterTree({
  activeProject, volumes, expandedVolumes, setExpandedVolumes,
  handleSelectChapter,
}) {
  const { t, language } = useApp()
  return (
    <div className="chapter-items">
      {volumes.length > 0 ? (
        volumes.map(vol => {
          const volChapters = (activeProject.chapters || []).filter(c =>
            c.chapter_index >= vol.startChapter && c.chapter_index <= vol.endChapter
          )
          const isExpanded = expandedVolumes[vol.num]
          const doneCount = volChapters.filter(c => c.status === "completed" || c.word_count > 0).length
          return (
            <div key={vol.num} className="volume-group">
              <AccessibleButton
                className="volume-header"
                onClick={() => setExpandedVolumes(prev => ({ ...prev, [vol.num]: !prev[vol.num] }))}
                style={{
                  background: isExpanded ? "var(--bg-active, rgba(99,102,241,0.1))" : "transparent",
                }}
              >
                <span>
                  <span style={{ display: "inline-block", width: 12, transition: "transform 0.15s", transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)" }}>▶</span>
                  {" "}{language === "zh" ? `第${vol.num}卷` : `Vol ${vol.num}`} · {vol.name}
                </span>
                <span className="preset-hint">
                  {doneCount}/{volChapters.length || (vol.endChapter - vol.startChapter + 1)} {t("ch")}
                </span>
              </AccessibleButton>
              {isExpanded && (
                <div className="volume-chapters">
                  {volChapters.length > 0 ? volChapters.map(c => (
                    <div key={c.chapter_index} className="chapter-item"
                      onClick={() => handleSelectChapter(c)}>
                      <div className="chapter-item-num">{c.chapter_index}</div>
                      <div className="chapter-item-name">{c.title || t("untitled")}</div>
                    </div>
                  )) : (
                    <div className="chapter-list-empty" style={{ padding: "8px 16px", fontSize: 11 }}>
                      {t("noChaptersInVolume")}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })
      ) : (
        // 无分卷信息时，平铺显示
        (activeProject.chapters || []).map((c) => (
          <div key={c.chapter_index} className="chapter-item"
            onClick={() => handleSelectChapter(c)}>
            <div className="chapter-item-num">{c.chapter_index}</div>
            <div className="chapter-item-name">{c.title || t("untitled")}</div>
          </div>
        ))
      )}
      {activeProject.chapters?.length === 0 && volumes.length === 0 && (
        <div className="chapter-list-empty">{t("noChapters")}</div>
      )}
    </div>
  )
}
