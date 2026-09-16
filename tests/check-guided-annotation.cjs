// Run: node tests/check-guided-annotation.cjs
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('tools/guided-annotation.html','utf8');
const context=vm.createContext({BATCH:{artifact_id:'batch',questions:[{id:'Q01'},{id:'Q02'}]}});
vm.runInContext(html.slice(html.indexOf('function validateAnswers'),html.indexOf('let data=')),context);
const answer={status:'readable',item:'磁鐵',count:'001',reviewer:'human',answered_at:'2026-09-16T01:00:00Z'};
const data={schema:'dsp-guided-annotation-answers/1',batch_id:'batch',status:'pending',training_authorized:false,answers:{Q01:answer}};
assert.equal(context.validateAnswers(JSON.parse(JSON.stringify(data))).answers.Q01.count,'001');
for(const change of [d=>d.batch_id='other',d=>d.training_authorized=true,d=>d.answers.Q99=answer,d=>d.answers.Q01.count='1e2',d=>d.answers.Q01.count=1,d=>d.answers.Q01.answered_at='2026-09-16T01:00:00',d=>d.answers.Q01.reviewer='',d=>d.answers.Q01.status='wrong_target']){const bad=structuredClone(data);change(bad);assert.throws(()=>context.validateAnswers(bad));}
for(const status of ['unreadable','wrong_target'])context.validateAnswers({...data,answers:{Q01:{...answer,status,item:null,count:null}}});
const nodes={progress:{},export:{},prev:{},next:{}};
Object.assign(context,{data,dirty:false,pos:0,$:id=>nodes[id]});
vm.runInContext(html.match(/function progress[^\n]+/)[0],context);
context.progress();assert.equal(nodes.export.disabled,false);assert.equal(nodes.next.disabled,false);
context.dirty=true;context.progress();assert.equal(nodes.export.disabled,true);assert.equal(nodes.next.disabled,true);
console.log('guided answer provenance, uncertainty, persistence round-trip and unfinished-edit checks passed');
