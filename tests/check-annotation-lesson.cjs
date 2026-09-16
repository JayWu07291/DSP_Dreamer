// Run: node tests/check-annotation-lesson.cjs
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('tools/annotation-lesson.html','utf8');
const code=html.slice(html.indexOf('function pictureAnswer'),html.indexOf('function mark'));
const context=vm.createContext({});vm.runInContext(code,context);
assert.equal(context.pictureAnswer('clear','iron','10').count,10);
assert.equal(context.pictureAnswer('unclear','iron','10').count,null);
for(const value of ['', '1.5', '-1', '1e2', 'Infinity'])assert.throws(()=>context.pictureAnswer('clear','iron',value));
assert.throws(()=>context.pictureAnswer('clear','unknown','10'));
assert.throws(()=>context.pictureAnswer('','iron','10'));
assert.equal(context.sequenceAnswer('empty','present','ui').after,'present');
assert.equal(context.sequenceAnswer('unclear','present','unclear').before,'unclear');
assert.throws(()=>context.sequenceAnswer('empty','','ui'));
assert.throws(()=>context.sequenceAnswer('empty','present','build'));
assert.equal(context.stepIndex(-4),0);assert.equal(context.stepIndex(7.7),8);assert.equal(context.stepIndex(30),15);
// An unfinished edit must not be silently omitted from an exported answer set.
const nodes={progress:{},download:{}};
Object.assign(context, {answers:{picture:{count:10},sequence:null},pendingEdits:new Set(),$:id=>nodes[id]});
vm.runInContext(html.match(/function updateProgress[^\n]+/)[0],context);
context.updateProgress();assert.equal(nodes.download.disabled,false);
context.pendingEdits.add('sequence');context.updateProgress();assert.equal(nodes.download.disabled,true);
console.log('lesson answer and timeline checks passed');
