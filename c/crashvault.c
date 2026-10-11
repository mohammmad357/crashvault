/* CrashVault C11: framed append log + open-addressed in-memory index. */
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <io.h>
#define SYNC(fd) _commit(fd)
#define FILENO(f) _fileno(f)
#else
#include <sys/types.h>
#include <unistd.h>
#define SYNC(fd) fsync(fd)
#define FILENO(f) fileno(f)
#endif

#define MAX_KEY 1024u
#define MAX_VALUE 65536u
#define MAX_PAYLOAD (7u + MAX_KEY + MAX_VALUE)
static const unsigned char MAGIC[8] = {'C','V','L','T',1,0,0,0};
typedef struct { char *key, *value; unsigned char state; } Slot;
typedef struct { Slot *slots; size_t capacity, used, occupied; } Index;
typedef struct { FILE *file; Index index; size_t records; long recovered; int sync; } Store;
static void fail(const char *message) { fprintf(stderr, "%s\n", message); exit(2); }
static void *allocate(size_t size) { void *p = malloc(size); if (!p) fail("out of memory"); return p; }
static char *copy(const char *text) { size_t n = strlen(text)+1; char *p=allocate(n); memcpy(p,text,n); return p; }
static uint32_t read32(const unsigned char *p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static void write32(unsigned char *p, uint32_t n) { for (int i=0;i<4;++i) p[i]=(unsigned char)(n>>(8*i)); }
static uint32_t crc_table[256];
static void init_crc(void) {
    for (uint32_t i=0;i<256;++i) { uint32_t c=i; for(int k=0;k<8;++k) c=(c>>1)^((c&1)?UINT32_C(0xedb88320):0); crc_table[i]=c; }
}
static uint32_t crc32(const unsigned char *p,size_t n) {
    uint32_t c=UINT32_C(0xffffffff);
    for(size_t i=0;i<n;++i) c=(c>>8)^crc_table[(c^p[i])&255];
    return c^UINT32_C(0xffffffff);
}
static uint64_t hash(const char *key) {
    uint64_t h=UINT64_C(14695981039346656037);
    for(;*key;++key) { h^=(unsigned char)*key; h*=UINT64_C(1099511628211); }
    return h;
}
static size_t locate(Index *index,const char *key,int insertion) {
    size_t i=(size_t)hash(key)&(index->capacity-1), tomb=SIZE_MAX;
    while(index->slots[i].state) {
        if(index->slots[i].state==1 && !strcmp(index->slots[i].key,key)) return i;
        if(index->slots[i].state==2 && tomb==SIZE_MAX) tomb=i;
        i=(i+1)&(index->capacity-1);
    }
    return insertion && tomb!=SIZE_MAX ? tomb : i;
}
static void resize(Index *index,size_t capacity) {
    Slot *old=index->slots; size_t previous=index->capacity;
    index->slots=allocate(capacity*sizeof *index->slots); memset(index->slots,0,capacity*sizeof *index->slots);
    index->capacity=capacity; index->occupied=index->used;
    for(size_t i=0;i<previous;++i) if(old[i].state==1) index->slots[locate(index,old[i].key,1)]=old[i];
    free(old);
}
static void set(Index *index,const char *key,const char *value) {
    if((index->occupied+1)*10 >= index->capacity*7) resize(index,index->used>=index->capacity/2 ? index->capacity*2 : index->capacity);
    size_t i=locate(index,key,1); Slot *slot=&index->slots[i];
    if(slot->state==1) { free(slot->value); slot->value=copy(value); }
    else { if(!slot->state) ++index->occupied; slot->key=copy(key); slot->value=copy(value); slot->state=1; ++index->used; }
}
static int erase(Index *index,const char *key) {
    Slot *slot=&index->slots[locate(index,key,0)];
    if(slot->state!=1) return 0;
    free(slot->key); free(slot->value); slot->key=NULL; slot->value=NULL; slot->state=2; --index->used; return 1;
}
static void validate(const char *text,size_t maximum,int empty) {
    size_t n=strlen(text); if(n>maximum || (!empty && !n)) fail("field length outside supported range");
    for(size_t i=0;i<n;++i) if((unsigned char)text[i]<32 || (unsigned char)text[i]>126) fail("fields must contain printable ASCII only");
}
static void flush(Store *store) {
    if(fflush(store->file)) fail("flush failed; acknowledgment not issued");
    if(store->sync && SYNC(FILENO(store->file))) fail("sync failed; acknowledgment not issued");
}
static void truncate_log(FILE *file,long length) {
#ifdef _WIN32
    if(_chsize_s(FILENO(file),(long long)length)) fail("truncate failed");
#else
    if(ftruncate(FILENO(file),(off_t)length)) fail("truncate failed");
#endif
    if(fseek(file,length,SEEK_SET)) fail("seek failed");
}
static void recover(Store *store) {
    FILE *file=store->file;
    if(fseek(file,0,SEEK_END)) fail("seek failed");
    long original=ftell(file); if(original<0) fail("file size unavailable"); rewind(file);
    unsigned char header[8]; size_t count=fread(header,1,8,file);
    if(ferror(file)) fail("read failed");
    if(count<8) {
        if(memcmp(header,MAGIC,count)) fail("invalid partial file header");
        store->recovered=(long)count; truncate_log(file,0);
        if(fwrite(MAGIC,1,8,file)!=8) fail("write failed");
        flush(store); return;
    }
    if(memcmp(header,MAGIC,8)) fail("invalid file header or unsupported version");
    long good_end=8; unsigned char *frame=allocate(MAX_PAYLOAD+4);
    while(1) {
        count=fread(header,1,8,file); if(ferror(file)) fail("read failed"); if(count<8) break;
        uint32_t length=read32(header);
        if(read32(header+4)!=(length^UINT32_C(0xffffffff)) || length<8 || length>MAX_PAYLOAD) fail("invalid frame length");
        count=fread(frame,1,(size_t)length+4,file); if(ferror(file)) fail("read failed"); if(count<length+4u) break;
        if(crc32(frame,length)!=read32(frame+length)) fail("checksum mismatch");
        unsigned int op=frame[0], nk=(unsigned int)frame[1]|((unsigned int)frame[2]<<8); uint32_t nv=read32(frame+3);
        if((op!=1 && op!=2) || !nk || nk>MAX_KEY || nv>MAX_VALUE || 7u+nk+nv!=length || (op==2 && nv)) fail("invalid record fields");
        for(uint32_t i=7;i<length;++i) if(frame[i]<32 || frame[i]>126) fail("invalid record text");
        char *key=allocate(nk+1u), *value=allocate((size_t)nv+1);
        memcpy(key,frame+7,nk); key[nk]=0; memcpy(value,frame+7+nk,nv); value[nv]=0;
        if(op==1) set(&store->index,key,value); else erase(&store->index,key);
        free(key); free(value); ++store->records;
        if(good_end>2147483647L-(long)length-12) fail("log exceeds supported 2 GiB limit");
        good_end+=(long)length+12;
    }
    free(frame); store->recovered=original-good_end;
    if(store->recovered) { truncate_log(file,good_end); flush(store); }
    if(fseek(file,0,SEEK_END)) fail("seek failed");
}
static void append(Store *store,unsigned char operation,const char *key,const char *value) {
    validate(key,MAX_KEY,0); validate(value,MAX_VALUE,1);
    size_t nk=strlen(key),nv=strlen(value),length=7+nk+nv,total=length+12;
    long offset=ftell(store->file);
    if(offset<0 || offset>2147483647L-(long)total) fail("log exceeds supported 2 GiB limit");
    unsigned char *frame=allocate(total); write32(frame,(uint32_t)length); write32(frame+4,(uint32_t)length^UINT32_C(0xffffffff)); frame[8]=operation;
    frame[9]=(unsigned char)nk; frame[10]=(unsigned char)(nk>>8); write32(frame+11,(uint32_t)nv);
    memcpy(frame+15,key,nk); memcpy(frame+15+nk,value,nv); write32(frame+8+length,crc32(frame+8,length));
    if(fwrite(frame,1,total,store->file)!=total) fail("write failed; acknowledgment not issued");
    flush(store); free(frame); ++store->records;
}
static void quote(const char *text) {
    putchar('"'); for(;*text;++text) { if(*text=='"' || *text=='\\') putchar('\\'); putchar(*text); } putchar('"');
}
int main(int argc,char **argv) {
    if(argc<2 || argc>3 || (argc==3 && strcmp(argv[2],"--no-sync"))) fail("usage: crashvault FILE [--no-sync]");
    init_crc(); Store store={0}; store.sync=argc==2;
    store.file=fopen(argv[1],"r+b");
    if(!store.file) { if(errno!=ENOENT) fail("cannot open log"); store.file=fopen(argv[1],"w+bx"); if(!store.file) fail("cannot create log"); }
    resize(&store.index,64); recover(&store);
    size_t capacity=MAX_KEY+MAX_VALUE+16; char *line=allocate(capacity);
    while(fgets(line,(int)capacity,stdin)) {
        size_t length=strlen(line);
        if(length && line[length-1]!='\n' && !feof(stdin)) fail("command too long");
        while(length && (line[length-1]=='\n' || line[length-1]=='\r')) line[--length]=0;
        char *first=strchr(line,'\t'), *key=NULL,*value=NULL;
        if(first) { *first=0; key=first+1; char *second=strchr(key,'\t'); if(second) { *second=0; value=second+1; } }
        if(!strcmp(line,"PUT") && key && value && !strchr(value,'\t')) {
            append(&store,1,key,value); set(&store.index,key,value); puts("{\"ok\":true}");
        } else if(!strcmp(line,"GET") && key && !value) {
            validate(key,MAX_KEY,0); Slot *slot=&store.index.slots[locate(&store.index,key,0)];
            printf("{\"value\":"); if(slot->state==1) quote(slot->value); else printf("null"); puts("}");
        } else if(!strcmp(line,"DEL") && key && !value) {
            append(&store,2,key,""); printf("{\"deleted\":%s}\n",erase(&store.index,key)?"true":"false");
        } else if(!strcmp(line,"STATS") && !key) {
            printf("{\"keys\":%zu,\"records\":%zu,\"recovered_bytes\":%ld,\"file_bytes\":%ld}\n",store.index.used,store.records,store.recovered,ftell(store.file));
        } else fail("invalid command");
        if(fflush(stdout)) fail("output failed");
    }
    if(ferror(stdin)) fail("input failed");
    free(line);
    for(size_t i=0;i<store.index.capacity;++i) if(store.index.slots[i].state==1) { free(store.index.slots[i].key); free(store.index.slots[i].value); }
    free(store.index.slots);
    if(fclose(store.file)) fail("close failed");
    return 0;
}
