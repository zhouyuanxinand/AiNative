/** Hero 区域——标题 + 指标。 */
export function Hero() {
  return (
    <section className="hero">
      <div>
        <div className="eyebrow">Controlled document automation</div>
        <h2>从原始技术文档到可审计的研制任务书</h2>
        <p>
          按语义识别整章节内容，连同表格、图片与图题原样写入正确模板位置。大模型只做分类与路由判断，不生成、不总结、不改写技术正文。
        </p>
      </div>
      <div className="hero-metrics">
        <div className="metric">
          <strong>20</strong>
          <span>受控语义类别</span>
        </div>
        <div className="metric">
          <strong>18</strong>
          <span>产品类型目录</span>
        </div>
        <div className="metric">
          <strong>2</strong>
          <span>用户输入文件</span>
        </div>
      </div>
    </section>
  );
}
