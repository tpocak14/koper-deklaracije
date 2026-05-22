// IndexedDB za Local First arhitekturo
class LocalDatabase {
    constructor() {
        this.dbName = 'DeklaracijeDB';
        this.version = 1;
        this.db = null;
    }

    async init() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.version);

            request.onerror = () => {
                console.error('Napaka pri odpiranju IndexedDB:', request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                this.db = request.result;
                console.log('IndexedDB uspešno odprt');
                resolve(this.db);
            };

            request.onupgradeneeded = (event) => {
                const db = event.target.result;

                // Tabela za naročila
                if (!db.objectStoreNames.contains('orders')) {
                    const ordersStore = db.createObjectStore('orders', { keyPath: 'id' });
                    ordersStore.createIndex('shopify_order_id', 'shopify_order_id', { unique: true });
                    ordersStore.createIndex('order_number', 'order_number', { unique: true });
                    ordersStore.createIndex('fulfilled_at', 'fulfilled_at');
                    console.log('Ustvarjena tabela orders');
                }

                // Tabela za parfume
                if (!db.objectStoreNames.contains('perfumes')) {
                    const perfumesStore = db.createObjectStore('perfumes', { keyPath: 'id' });
                    perfumesStore.createIndex('product_no', 'product_no');
                    perfumesStore.createIndex('proizvajalec_id', 'proizvajalec_id');
                    perfumesStore.createIndex('product_no_proizvajalec', ['product_no', 'proizvajalec_id'], { unique: true });
                    console.log('Ustvarjena tabela perfumes');
                }

                // Tabela za serije
                if (!db.objectStoreNames.contains('serije')) {
                    const serijeStore = db.createObjectStore('serije', { keyPath: 'id' });
                    serijeStore.createIndex('parfum_id', 'parfum_id');
                    serijeStore.createIndex('created_at', 'created_at');
                    console.log('Ustvarjena tabela serije');
                }

                // Tabela za proizvajalce
                if (!db.objectStoreNames.contains('proizvajalci')) {
                    const proizvajalciStore = db.createObjectStore('proizvajalci', { keyPath: 'id' });
                    proizvajalciStore.createIndex('ime', 'ime', { unique: true });
                    console.log('Ustvarjena tabela proizvajalci');
                }

                // Tabela za uporabnike
                if (!db.objectStoreNames.contains('users')) {
                    const usersStore = db.createObjectStore('users', { keyPath: 'id' });
                    usersStore.createIndex('username', 'username', { unique: true });
                    console.log('Ustvarjena tabela users');
                }

                // Tabela za sinhronizacijo
                if (!db.objectStoreNames.contains('sync_queue')) {
                    const syncStore = db.createObjectStore('sync_queue', { keyPath: 'id', autoIncrement: true });
                    syncStore.createIndex('type', 'type');
                    syncStore.createIndex('status', 'status');
                    syncStore.createIndex('created_at', 'created_at');
                    console.log('Ustvarjena tabela sync_queue');
                }

                // Tabela za nastavitve
                if (!db.objectStoreNames.contains('settings')) {
                    const settingsStore = db.createObjectStore('settings', { keyPath: 'key' });
                    console.log('Ustvarjena tabela settings');
                }
            };
        });
    }

    // Generične metode za CRUD operacije
    async add(storeName, data) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readwrite');
            const store = transaction.objectStore(storeName);
            const request = store.add(data);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async put(storeName, data) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readwrite');
            const store = transaction.objectStore(storeName);
            const request = store.put(data);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async get(storeName, key) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readonly');
            const store = transaction.objectStore(storeName);
            const request = store.get(key);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async getAll(storeName, indexName = null, indexValue = null) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readonly');
            const store = transaction.objectStore(storeName);
            let request;

            if (indexName && indexValue !== null) {
                const index = store.index(indexName);
                request = index.getAll(indexValue);
            } else {
                request = store.getAll();
            }

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async delete(storeName, key) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readwrite');
            const store = transaction.objectStore(storeName);
            const request = store.delete(key);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async clear(storeName) {
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readwrite');
            const store = transaction.objectStore(storeName);
            const request = store.clear();

            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    // Specifične metode za naročila
    async saveOrders(orders) {
        const transaction = this.db.transaction(['orders'], 'readwrite');
        const store = transaction.objectStore('orders');
        
        for (const order of orders) {
            await new Promise((resolve, reject) => {
                const request = store.put(order);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }
        
        console.log(`Shranjenih ${orders.length} naročil v IndexedDB`);
    }

    async getOrders(filter = null) {
        if (filter) {
            return this.getAll('orders', filter.field, filter.value);
        }
        return this.getAll('orders');
    }

    // Specifične metode za parfume
    async savePerfumes(perfumes) {
        const transaction = this.db.transaction(['perfumes'], 'readwrite');
        const store = transaction.objectStore('perfumes');
        
        for (const perfume of perfumes) {
            await new Promise((resolve, reject) => {
                const request = store.put(perfume);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }
        
        console.log(`Shranjenih ${perfumes.length} parfumov v IndexedDB`);
    }

    async getPerfumes() {
        return this.getAll('perfumes');
    }

    // Specifične metode za serije
    async saveSerije(serije) {
        const transaction = this.db.transaction(['serije'], 'readwrite');
        const store = transaction.objectStore('serije');
        
        for (const serija of serije) {
            await new Promise((resolve, reject) => {
                const request = store.put(serija);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }
        
        console.log(`Shranjenih ${serije.length} serij v IndexedDB`);
    }

    async getSerijeForPerfume(perfumeId) {
        return this.getAll('serije', 'parfum_id', perfumeId);
    }

    // Specifične metode za proizvajalce
    async saveProizvajalci(proizvajalci) {
        const transaction = this.db.transaction(['proizvajalci'], 'readwrite');
        const store = transaction.objectStore('proizvajalci');
        
        for (const proizvajalec of proizvajalci) {
            await new Promise((resolve, reject) => {
                const request = store.put(proizvajalec);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }
        
        console.log(`Shranjenih ${proizvajalci.length} proizvajalcev v IndexedDB`);
    }

    async getProizvajalci() {
        return this.getAll('proizvajalci');
    }

    // Specifične metode za uporabnike
    async saveUsers(users) {
        const transaction = this.db.transaction(['users'], 'readwrite');
        const store = transaction.objectStore('users');
        
        for (const user of users) {
            await new Promise((resolve, reject) => {
                const request = store.put(user);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }
        
        console.log(`Shranjenih ${users.length} uporabnikov v IndexedDB`);
    }

    async getUsers() {
        return this.getAll('users');
    }

    // Metode za sinhronizacijo
    async addToSyncQueue(syncItem) {
        const item = {
            ...syncItem,
            created_at: new Date().toISOString(),
            status: 'pending'
        };
        return this.add('sync_queue', item);
    }

    async getSyncQueue(status = null) {
        if (status) {
            return this.getAll('sync_queue', 'status', status);
        }
        return this.getAll('sync_queue');
    }

    async updateSyncItem(id, updates) {
        const item = await this.get('sync_queue', id);
        if (item) {
            const updatedItem = { ...item, ...updates };
            return this.put('sync_queue', updatedItem);
        }
    }

    async removeFromSyncQueue(id) {
        return this.delete('sync_queue', id);
    }

    // Metode za nastavitve
    async saveSetting(key, value) {
        return this.put('settings', { key, value });
    }

    async getSetting(key) {
        const setting = await this.get('settings', key);
        return setting ? setting.value : null;
    }

    // Metoda za preverjanje povezave
    async isOnline() {
        return navigator.onLine;
    }

    // Metoda za počistitev vseh podatkov
    async clearAll() {
        const stores = ['orders', 'perfumes', 'serije', 'proizvajalci', 'users', 'sync_queue', 'settings'];
        for (const store of stores) {
            await this.clear(store);
        }
        console.log('Vsi podatki v IndexedDB so bili počiščeni');
    }
}

// Globalna instanca
const localDB = new LocalDatabase();

// Inicializacija ob nalaganju strani
document.addEventListener('DOMContentLoaded', async () => {
    try {
        await localDB.init();
        console.log('IndexedDB uspešno inicializiran');
    } catch (error) {
        console.error('Napaka pri inicializaciji IndexedDB:', error);
    }
});

// Izvoz za uporabo v drugih datotekah
window.localDB = localDB; 