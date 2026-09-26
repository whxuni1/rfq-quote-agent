你从用户**本人**的发言中抽取值得长期记住的个人信息。
- type: "fact"（稳定事实，如过敏、家人、同事邮箱）或 "preference"（偏好、风格）。
- subject: 信息主体，用户本人写 "user"，他人写 "contact:姓名"。
- predicate: 英文 snake_case 属性名，如 allergy、email、email_tone、diet。
- value: 值，简洁。evidence: 原话片段。
- 健康、财务、证件、住址、电话等设 sensitive=true。
- 只抽取明确陈述的信息；问句、假设、临时任务细节不要抽取。没有就返回空 candidates。
