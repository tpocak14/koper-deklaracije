// Sync Manager za Local First arhitekturo
class SyncManager {
    constructor() {
        this.isOnline = navigator.onLine;
        this.syncInProgress = false;
        this.syncInterval = null;
        this.retryAttempts = 3;
        this.retryDelay = 5000; // 5 sekund
        
        this.setupEventListeners();
    }

    setupEventListeners() {
        // Preveri spremembe povezave
        window.addEventListener('online', () => {
            console.log('Povezava vzpostavljena - začenjam sinhronizacijo');
            this.isOnline = true;
            this.syncAll();
        });

        window.addEventListener('offline', () => {
            console.log('Povezava prekinjena - sinhronizacija zaustavljena');
            this.isOnline = false;
        });

        // Periodična sinhronizacija (vsakih 30 sekund)
        this.syncInterval = setInterval(() => {
            if (this.isOnline && !this.syncInProgress) {
                this.syncAll();
            }
        }, 30000);
    }

    async syncAll() {
        if (this.syncInProgress || !this.isOnline) {
            return;
        }

        this.syncInProgress = true;
        console.log('Začenjam sinhronizacijo...');

        try {
            // 1. Sinhroniziraj naročila
            await this.syncOrders();
            
            // 2. Sinhroniziraj parfume
            await this.syncPerfumes();
            
            // 3. Sinhroniziraj serije
            await this.syncSerije();
            
            // 4. Sinhroniziraj proizvajalce
            await this.syncProizvajalci();
            
            // 5. Sinhroniziraj uporabnike (samo za admina); navadni userji dobijo seznam prek /api/nalivalci po potrebi
            try {
                const cu = JSON.parse(localStorage.getItem('currentUser')||'{}');
                const role = (cu.role||'').toLowerCase();
                if (role === 'admin') {
                    await this.syncUsers();
                }
            } catch(_) {}
            
            // 6. Obdelaj sync queue
            await this.processSyncQueue();

            console.log('Sinhronizacija uspešno dokončana');
            
        } catch (error) {
            console.error('Napaka pri sinhronizaciji:', error);
        } finally {
            this.syncInProgress = false;
        }
    }

                    async syncOrders() {
                    try {
                        // Pridobi naročila iz strežnika
                        const response = await fetch('/api/narocila?per_page=200');
                        if (response.ok) {
                            const data = await response.json();
                            if (data.narocila && Array.isArray(data.narocila)) {
                                await localDB.saveOrders(data.narocila);
                                console.log(`Sinhroniziranih ${data.narocila.length} naročil`);
                            } else {
                                console.error('Neveljaven format naročil:', data);
                            }
                        }
                    } catch (error) {
                        console.error('Napaka pri sinhronizaciji naročil:', error);
                    }
                }

                    async syncPerfumes() {
                    try {
                        // Pridobi parfume iz strežnika
                        const response = await fetch('/api/parfumi');
                        if (response.ok) {
                            const perfumes = await response.json();
                            if (Array.isArray(perfumes)) {
                                await localDB.savePerfumes(perfumes);
                                console.log(`Sinhroniziranih ${perfumes.length} parfumov`);
                            } else {
                                console.error('Neveljaven format parfumov:', perfumes);
                            }
                        }
                    } catch (error) {
                        console.error('Napaka pri sinhronizaciji parfumov:', error);
                    }
                }

                    async syncSerije() {
                    try {
                        // Pridobi vse serije iz strežnika
                        const response = await fetch('/api/serije');
                        if (response.ok) {
                            const serije = await response.json();
                            if (Array.isArray(serije)) {
                                await localDB.saveSerije(serije);
                                console.log(`Sinhroniziranih ${serije.length} serij`);
                            } else {
                                console.error('Neveljaven format serij:', serije);
                            }
                        }
                    } catch (error) {
                        console.error('Napaka pri sinhronizaciji serij:', error);
                    }
                }

                    async syncProizvajalci() {
                    try {
                        // Pridobi proizvajalce iz strežnika
                        const response = await fetch('/api/proizvajalci');
                        if (response.ok) {
                            const proizvajalci = await response.json();
                            if (Array.isArray(proizvajalci)) {
                                await localDB.saveProizvajalci(proizvajalci);
                                console.log(`Sinhroniziranih ${proizvajalci.length} proizvajalcev`);
                            } else {
                                console.error('Neveljaven format proizvajalcev:', proizvajalci);
                            }
                        }
                    } catch (error) {
                        console.error('Napaka pri sinhronizaciji proizvajalcev:', error);
                    }
                }

                    async syncUsers() {
                    try {
                        // Pridobi uporabnike iz strežnika
                        const response = await fetch('/api/users');
                        if (response.ok) {
                            const users = await response.json();
                            if (Array.isArray(users)) {
                                await localDB.saveUsers(users);
                                console.log(`Sinhroniziranih ${users.length} uporabnikov`);
                            } else {
                                console.error('Neveljaven format uporabnikov:', users);
                            }
                        }
                    } catch (error) {
                        console.error('Napaka pri sinhronizaciji uporabnikov:', error);
                    }
                }

    async processSyncQueue() {
        try {
            const pendingItems = await localDB.getSyncQueue('pending');
            
            for (const item of pendingItems) {
                await this.processSyncItem(item);
            }
        } catch (error) {
            console.error('Napaka pri obdelavi sync queue:', error);
        }
    }

    async processSyncItem(item) {
        try {
            let response;
            
            switch (item.type) {
                case 'add_serija':
                    response = await fetch('/api/serije', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(item.data)
                    });
                    break;
                    
                case 'update_serija':
                    response = await fetch(`/api/serije/${item.data.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(item.data)
                    });
                    break;
                    
                case 'delete_serija':
                    response = await fetch(`/api/serije/${item.data.id}`, {
                        method: 'DELETE'
                    });
                    break;
                    
                case 'add_perfume':
                    response = await fetch('/api/parfumi', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(item.data)
                    });
                    break;
                    
                case 'update_perfume':
                    response = await fetch(`/api/parfum/${item.data.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(item.data)
                    });
                    break;
                    
                default:
                    console.warn('Neznan tip sync item:', item.type);
                    return;
            }
            
            if (response && response.ok) {
                // Uspešno sinhronizirano
                await localDB.updateSyncItem(item.id, { 
                    status: 'completed',
                    synced_at: new Date().toISOString()
                });
                console.log(`Uspešno sinhroniziran ${item.type}`);
            } else {
                // Preveri, ali gre za konflikt
                if (response.status === 409) {
                    // Konflikt - obdelaj ga
                    await this.handleConflict(item, response);
                } else {
                    // Neuspešno - poskusi ponovno
                    await this.retrySyncItem(item);
                }
            }
            
        } catch (error) {
            console.error(`Napaka pri obdelavi sync item ${item.type}:`, error);
            await this.retrySyncItem(item);
        }
    }

    async retrySyncItem(item) {
        const retryCount = item.retry_count || 0;
        
        if (retryCount < this.retryAttempts) {
            await localDB.updateSyncItem(item.id, {
                status: 'retry',
                retry_count: retryCount + 1,
                last_retry: new Date().toISOString()
            });
            
            // Poskusi ponovno po zamiku
            setTimeout(() => {
                this.processSyncItem(item);
            }, this.retryDelay * (retryCount + 1));
        } else {
            // Presegel maksimalno število poskusov
            await localDB.updateSyncItem(item.id, {
                status: 'failed',
                failed_at: new Date().toISOString()
            });
            console.error(`Sync item ${item.type} je neuspešen po ${this.retryAttempts} poskusih`);
        }
    }

    // Metode za dodajanje v sync queue
    async queueAddSerija(serijaData) {
        await localDB.addToSyncQueue({
            type: 'add_serija',
            data: serijaData
        });
    }

    async queueUpdateSerija(serijaData) {
        await localDB.addToSyncQueue({
            type: 'update_serija',
            data: serijaData
        });
    }

    async queueDeleteSerija(serijaId) {
        await localDB.addToSyncQueue({
            type: 'delete_serija',
            data: { id: serijaId }
        });
    }

    async queueAddPerfume(perfumeData) {
        await localDB.addToSyncQueue({
            type: 'add_perfume',
            data: perfumeData
        });
    }

    async queueUpdatePerfume(perfumeData) {
        await localDB.addToSyncQueue({
            type: 'update_perfume',
            data: perfumeData
        });
    }

    // Metoda za ročno sinhronizacijo
    async manualSync() {
        console.log('Ročna sinhronizacija...');
        await this.syncAll();
    }

    // Metoda za preverjanje stanja sinhronizacije
    async getSyncStatus() {
        const pendingItems = await localDB.getSyncQueue('pending');
        const retryItems = await localDB.getSyncQueue('retry');
        const failedItems = await localDB.getSyncQueue('failed');
        
        return {
            isOnline: this.isOnline,
            syncInProgress: this.syncInProgress,
            pending: pendingItems.length,
            retry: retryItems.length,
            failed: failedItems.length
        };
    }

    // Metoda za čiščenje sync queue
    async clearSyncQueue() {
        await localDB.clear('sync_queue');
        console.log('Sync queue počiščen');
    }

    // Metoda za ponovno poskusitev neuspešnih elementov
                    async retryFailedItems() {
                    const failedItems = await localDB.getSyncQueue('failed');
                    
                    for (const item of failedItems) {
                        await localDB.updateSyncItem(item.id, {
                            status: 'pending',
                            retry_count: 0
                        });
                    }
                    
                    console.log(`Ponovno poskušam ${failedItems.length} neuspešnih elementov`);
                    await this.processSyncQueue();
                }
                
                // Conflict resolution
                async handleConflict(item, response) {
                    try {
                        const conflictData = await response.json();
                        console.log(`Konflikt zaznan za ${item.type}:`, conflictData);
                        
                        // Dodaj v conflict queue za ročno obravnavo
                        await localDB.updateSyncItem(item.id, {
                            status: 'conflict',
                            conflict_data: conflictData,
                            conflict_at: new Date().toISOString()
                        });
                        
                        // Prikaži obvestilo uporabniku
                        if (window.showToast) {
                            window.showToast(`Konflikt pri sinhronizaciji ${item.type} - potrebna ročna obravnava`, 'warning');
                        }
                        
                    } catch (error) {
                        console.error('Napaka pri obravnavi konflikta:', error);
                        await this.retrySyncItem(item);
                    }
                }
                
                // Pridobi konflikte za prikaz
                async getConflicts() {
                    return await localDB.getSyncQueue('conflict');
                }
                
                // Rešitev konflikta - uporabnik izbere verzijo
                async resolveConflict(itemId, resolution) {
                    try {
                        const item = await localDB.get('sync_queue', itemId);
                        if (!item) {
                            throw new Error('Konfliktni element ni najden');
                        }
                        
                        switch (resolution) {
                            case 'local':
                                // Uporabi lokalno verzijo
                                await localDB.updateSyncItem(itemId, {
                                    status: 'pending',
                                    resolution: 'local'
                                });
                                break;
                                
                            case 'remote':
                                // Uporabi oddaljeno verzijo
                                await localDB.updateSyncItem(itemId, {
                                    status: 'completed',
                                    resolution: 'remote',
                                    synced_at: new Date().toISOString()
                                });
                                break;
                                
                            case 'merge':
                                // Poskusi združiti
                                await this.mergeConflict(item);
                                break;
                                
                            default:
                                throw new Error('Neznana rešitev konflikta');
                        }
                        
                        console.log(`Konflikt rešen z ${resolution} strategijo`);
                        
                    } catch (error) {
                        console.error('Napaka pri reševanju konflikta:', error);
                        throw error;
                    }
                }
                
                // Združevanje konfliktov
                async mergeConflict(item) {
                    try {
                        const conflictData = item.conflict_data;
                        
                        // Implementiraj logiko za združevanje glede na tip
                        switch (item.type) {
                            case 'add_serija':
                            case 'update_serija':
                                // Za serije - združi podatke
                                const mergedData = {
                                    ...item.data,
                                    ...conflictData.remote_data,
                                    merged_at: new Date().toISOString()
                                };
                                
                                await localDB.updateSyncItem(item.id, {
                                    status: 'pending',
                                    data: mergedData,
                                    resolution: 'merge'
                                });
                                break;
                                
                            default:
                                // Privzeto - uporabi lokalno verzijo
                                await localDB.updateSyncItem(item.id, {
                                    status: 'pending',
                                    resolution: 'local'
                                });
                        }
                        
                    } catch (error) {
                        console.error('Napaka pri združevanju konflikta:', error);
                        throw error;
                    }
                }

    // Uniči interval ob uničenju
    destroy() {
        if (this.syncInterval) {
            clearInterval(this.syncInterval);
        }
    }
}

// Globalna instanca
const syncManager = new SyncManager();

// Izvoz za uporabo v drugih datotekah
window.syncManager = syncManager; 