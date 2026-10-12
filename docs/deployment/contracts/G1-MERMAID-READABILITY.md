# G1-MERMAID-READABILITY 清洗后可信样式整改

- Task ID / Depends on / Base HEAD / Goal：S05-frontend-R2；Base42a5864c100e1bcd445118bc6d148c20f5453290，主控实际浏览器测出严格SVG清洗后flowchart node/text均rgb(0,0,0)，截图/tmp/newshub-mermaid-component.png与JSON同prefix；修复可读性且保留所有XSS安全限制。G1整改优先于G2源码准备。
- Owned files / Read-only references：frontend/src/components/news-detail/MermaidBlock.tsx（仅可信wrapper class）、frontend/src/index.css（新增局部静态CSS）、现MermaidBlock安全测试（路径实施者读取后准确返回）；只读既有DOMPurify/React技能/ADR/G1contracts。共用树不撤销他人、不派生，不改后端/其他UI。
- Decision frozen：securityLevel strict、htmlLabels false、DOMPurify禁style/script/foreignObject/a/image/use和href/xlink/style等全部保持；不允许SVG自带CSS、不放松FORBID_TAGS/ATTR、不重新bindFunctions。新增固定class newshub-mermaid仅成功图表wrapper，所有CSS选择器限定此wrapper内，不影响其他svg。可信静态palette：node rect/circle/ellipse/polygon/path fill #f4f0ff、stroke #7c3aed宽1.5px；text/tspan fill #111827，font-family inherit/font-size16px；cluster rect fill #f1f5f9 stroke #64748b；flowchart-link fill none/stroke #64748b宽1.5px；marker path fill/stroke #64748b；edge label背景rect fill #ffffff。svg display block、width auto、height auto、max-width100%、max-height32rem、flex none，保持viewBox/ARIA/清洗结果，不从不可信style拼CSS。此切片只恢复常见flowchart可读性，其他diagram视觉若发现缺口另契约，不猜大套主题。
- Implementation steps：1核对真实截图与现renderer安全链；2添加wrapperclass和静态局部CSS；3现安全测试加class断言，安全负例全部保留；4定向tests/typecheck/lint；5返回静态结果；主控随后实际组件浏览器截图/paint验收，再新G1SHA构建。
- Acceptance tests：cd frontend && npm run test:run -- 原MermaidBlock测试文件及Markdown安全测试 && npm run typecheck && npm run lint（准确文件读取后返回）；真实初始flowchart Fixture article --> Mermaid flow在primary isolated Vite+Chromium重新渲染，node/text fill不同、可见label与正常尺寸截图人工检查。实际浏览器由主控整合运行，实施者不能假报。
- Negative tests：恶意style/script/foreignObject/link/image/use/href仍无注入/bind；CSS不使用diagram里任意themeCSS/style/userclass作为外部selector；超text/edge限制不放松；CSS只在wrapper生效；不为通过测试强行mockpaint/browser。
- Forbidden：不降低sanitizer/strict、不新增依赖/iframe/允许inline styles、不真实API/域名系统修改/生产/用户DB，不commit/派生，两次失败交Sol。
- Return format：paths/diff/HEAD、定向命令exit/test数、保留安全策略、真实browser NOT_RUN及任何尺寸问题，不能把JSDOM通过当图表可读PASS。

## 实际浏览器第二项根因及R3
主控真实Chromium修复后node244/240/255、text17/24/39，危险元素/inline style0，配色正确；但截图/tmp/newshub-mermaid-component-r2.png显示文字从节点中心开始向右溢出，图形被放大到512px高度。原Mermaid内置style同时承载text-anchor与intrinsic max-width，不能仅修颜色就PASS。
Base c8de60835ab72fb2949664eab52004637537a6b2；相同3owned文件，扩充renderer ownership为以下**数字attribute规范化**，不动sanitizer配置。冻结CSS text/tspan新增text-anchor:middle；清洗后用独立template解析safeSvg，仅取svg的viewBox四个分隔数字，必须全部finite且width/height>0且<=10000，才把root width/height设置为对应正数十进制字符串（允许上取整），避免原width100%无限放大；无/坏viewBox不复制其他属性、不新增style，仅保留已清洗SVG。所有数字由Number验证，不拼任意字符串CSS，不允许危险tag/attr恢复；仍max-width100%/max-height32rem。序列化template的已清洗内容，其余markup安全断言保留。
新增定向测试有效viewBox尺寸成为数字width/height、坏数/Infinity/负尺寸/超10000/缺viewBox不normalize且无unsafe attr/style；CSS规则静态可信。真实browser由主控检查文字bbox在对应node shape内、label完整可见、root按viewBox正常尺寸、XSS限制不变。这是第二次有证据修复，若仍失败必须主控定位，不无限重试。
