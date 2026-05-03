"""
Simulador de Rede de Filas - Generalizado
Lê configuração de arquivo .yml e simula qualquer topologia de rede de filas.

Uso: python simulator.py run <modelo.yml>
"""

import yaml
import sys
import random
from collections import defaultdict




class RNG:
    """
    Gerador de números aleatórios com contagem de uso.
    Suporta lista fixa (rndnumbers) ou geração por seed.
    Encerra simulação ao atingir o limite.
    """
    def __init__(self, numbers=None, seed=None, limit=100000):
        self.limit = limit
        self.count = 0
        self.exhausted = False

        if numbers is not None:
            self.numbers = numbers
            self.use_list = True
        else:
            random.seed(seed)
            self.numbers = None
            self.use_list = False

    def next(self):
        """Retorna próximo número aleatório [0,1) ou None se esgotado."""
        if self.exhausted:
            return None
        if self.count >= self.limit:
            self.exhausted = True
            return None
        self.count += 1
        if self.use_list:
            idx = self.count - 1
            if idx >= len(self.numbers):
                self.exhausted = True
                return None
            return self.numbers[idx]
        else:
            return random.random()

    def uniform(self, a, b):
        """Gera valor uniforme [a, b] consumindo 1 aleatório."""
        u = self.next()
        if u is None:
            return None
        return a + u * (b - a)


# ==============================================================================
# ESTRUTURAS
# ==============================================================================

class Queue:
    """Representa uma fila G/G/c/K."""

    def __init__(self, name, servers, capacity, min_service, max_service,
                 min_arrival=None, max_arrival=None):
        self.name = name
        self.servers = servers
        self.capacity = capacity        # None = infinita
        self.min_service = min_service
        self.max_service = max_service
        self.min_arrival = min_arrival
        self.max_arrival = max_arrival

        # Estado atual
        self.clients = 0
        self.losses = 0

        # Contabilização de tempo por estado
        self.state_times = defaultdict(float)
        self.last_event_time = 0.0

    def is_full(self):
        if self.capacity is None:
            return False
        return self.clients >= self.capacity

    def servers_free(self):
        """Quantidade de servidores livres."""
        return max(0, self.servers - self.clients)

    def has_queue(self):
        """Há clientes aguardando (além dos em serviço)."""
        return self.clients > self.servers

    def accumulate(self, current_time):
        """Acumula tempo no estado atual antes de mudar."""
        elapsed = current_time - self.last_event_time
        if elapsed > 0:
            self.state_times[self.clients] += elapsed
        self.last_event_time = current_time

    def arrive(self, current_time):
        """
        Cliente tenta entrar na fila.
        Retorna True se entrou, False se perdido.
        """
        self.accumulate(current_time)
        if self.is_full():
            self.losses += 1
            return False
        self.clients += 1
        return True

    def depart(self, current_time):
        """Cliente termina serviço e sai da fila."""
        self.accumulate(current_time)
        self.clients -= 1

    def label(self):
        cap = f"/{self.capacity}" if self.capacity is not None else ""
        return f"G/G/{self.servers}{cap}"

    def finalize(self, end_time):
        self.accumulate(end_time)


class Event:
    ARRIVAL = 'arrival'
    DEPARTURE = 'departure'

    def __init__(self, kind, time, queue_idx):
        self.kind = kind
        self.time = time
        self.queue_idx = queue_idx

    def __lt__(self, other):
        return self.time < other.time


class Scheduler:
    """Escalonador de eventos (lista ordenada por tempo)."""

    def __init__(self):
        self.events = []

    def insert(self, event):
        import bisect
        bisect.insort(self.events, event)

    def next(self):
        return self.events.pop(0) if self.events else None

    def empty(self):
        return len(self.events) == 0


# ==============================================================================
# PARSER DO ARQUIVO YML
# ==============================================================================

def load_model(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace('!PARAMETERS', '')
    return yaml.safe_load(content)


def build_queues(data):
    """Constrói lista de filas e mapa nome->índice."""
    queues_cfg = data.get('queues', {})
    queue_list = []
    queue_index = {}

    for name, cfg in queues_cfg.items():
        q = Queue(
            name=name,
            servers=cfg.get('servers', 1),
            capacity=cfg.get('capacity', None),
            min_service=float(cfg.get('minService', 0)),
            max_service=float(cfg.get('maxService', 0)),
            min_arrival=float(cfg['minArrival']) if 'minArrival' in cfg else None,
            max_arrival=float(cfg['maxArrival']) if 'maxArrival' in cfg else None,
        )
        queue_index[name] = len(queue_list)
        queue_list.append(q)

    return queue_list, queue_index


def build_network(data, queue_index):
    """
    Monta tabela de roteamento.
    network[i] = lista de (prob_acumulada, idx_destino)
    idx_destino = -1 significa saída do sistema.
    """
    network_cfg = data.get('network', [])
    n = len(queue_index)
    raw = defaultdict(list)

    for route in network_cfg:
        src = queue_index[route['source']]
        tgt = queue_index[route['target']]
        prob = float(route['probability'])
        raw[src].append((prob, tgt))

    network = {}
    for src in range(n):
        routes = raw.get(src, [])
        acc = 0.0
        result = []
        for prob, tgt in routes:
            acc += prob
            result.append((acc, tgt))
        # Restante vai para o exterior
        if acc < 0.9999:
            result.append((1.0, -1))
        network[src] = result

    return network


def route(network, queue_idx, rng):
    """Sorteia destino para cliente saindo da fila queue_idx."""
    u = rng.next()
    if u is None:
        return None
    for prob_acc, dest in network[queue_idx]:
        if u < prob_acc:
            return dest
    return network[queue_idx][-1][1]



# SIMULAÇÃO

def simulate(queue_list, queue_index, network, data, rng):
    """
    Executa a simulação por eventos discretos.
    Encerra quando rng.exhausted == True.
    Retorna tempo global.
    """
    scheduler = Scheduler()

    # Primeira chegada: tempo definido em 'arrivals' ou min_arrival da fila
    arrivals_cfg = data.get('arrivals', {})
    for name, t in arrivals_cfg.items():
        if name in queue_index:
            scheduler.insert(Event(Event.ARRIVAL, float(t), queue_index[name]))

    # Filas com minArrival que não estejam em arrivals_cfg
    for name, idx in queue_index.items():
        q = queue_list[idx]
        if q.min_arrival is not None and name not in arrivals_cfg:
            scheduler.insert(Event(Event.ARRIVAL, q.min_arrival, idx))

    global_time = 0.0

    while not scheduler.empty():
        event = scheduler.next()
        global_time = event.time

        # CHEGADA 


        if event.kind == Event.ARRIVAL:
            q = queue_list[event.queue_idx]

            # Agenda próxima chegada externa ANTES de consumir mais aleatórios
            if q.min_arrival is not None:
                interval = rng.uniform(q.min_arrival, q.max_arrival)
                if interval is None:
                    # Aleatórios esgotados: registra chegada atual e encerra
                    q.arrive(global_time)
                    break
                scheduler.insert(Event(Event.ARRIVAL, global_time + interval, event.queue_idx))

            # Tenta inserir cliente na fila
            entered = q.arrive(global_time)

            if entered:
                # Se ha servidor livre inicia atendimento imediatamente
                if q.clients <= q.servers:
                    service = rng.uniform(q.min_service, q.max_service)
                    if service is None:
                        break
                    scheduler.insert(Event(Event.DEPARTURE, global_time + service, event.queue_idx))

        
        # EVENTO DE SAÍDA 

        elif event.kind == Event.DEPARTURE:
            q = queue_list[event.queue_idx]

            # Determina destino do cliente
            dest = route(network, event.queue_idx, rng)
            if dest is None:
                q.depart(global_time)
                break

            # Retira cliente da fila
            q.depart(global_time)

            # Se ainda há clientes aguardando, inicia próximo atendimento
            if q.clients >= q.servers:
                service = rng.uniform(q.min_service, q.max_service)
                if service is None:
                    break
                scheduler.insert(Event(Event.DEPARTURE, global_time + service, event.queue_idx))

            # Envia cliente ao destino
            if dest != -1:
                dest_q = queue_list[dest]
                entered = dest_q.arrive(global_time)
                if entered:
                    # Inicia atendimento se há servidor livre
                    if dest_q.clients <= dest_q.servers:
                        service = rng.uniform(dest_q.min_service, dest_q.max_service)
                        if service is None:
                            break
                        scheduler.insert(Event(Event.DEPARTURE, global_time + service, dest))

    # Finaliza acumulação de tempos
    for q in queue_list:
        q.finalize(global_time)

    return global_time




def print_report(queue_list, global_time, rng):
    sep = "=" * 57
    star = "*" * 57

    print(sep)
    print("=" * 22 + "    REPORT   " + "=" * 22)
    print(sep)

    for q in queue_list:
        print(star)
        print(f"Queue:   {q.name} ({q.label()})")
        if q.min_arrival is not None:
            print(f"Arrival: {q.min_arrival} ... {q.max_arrival}")
        print(f"Service: {q.min_service} ... {q.max_service}")
        print(star)

        total_time = sum(q.state_times.values())
        if not q.state_times:
            print("  (sem dados)")
            continue

        print(f"{'State':>9} {'Time':>20} {'Probability':>18}")
        for state in sorted(q.state_times.keys()):
            t = q.state_times[state]
            prob = (t / total_time * 100) if total_time > 0 else 0
            print(f"   {state:>6}   {t:>20.4f}   {prob:>14.2f}%")

        print(f"Number of losses: {q.losses}")

    print(sep)
    print(f"Simulation time: {global_time:.4f}")
    print(f"Random numbers used: {rng.count}")
    print(sep)



def run(model_file):
    sep = "=" * 57
    print(sep)
    print("=" * 12 + "   QUEUEING NETWORK SIMULATOR   " + "=" * 13)
    print("=" * 20 + "   version 2.0    " + "=" * 19)
    print(sep)

    data = load_model(model_file)
    queue_list, queue_index = build_queues(data)
    network = build_network(data, queue_index)

    limit = int(data.get('rndnumbersPerSeed', 100000))
    seeds = data.get('seeds', None)
    rnd_numbers = data.get('rndnumbers', None)

    if seeds:
        # Múltiplas simulações com seeds (compatibilidade com modelo do módulo 3)
        all_state_times = [defaultdict(float) for _ in queue_list]
        all_losses = [0] * len(queue_list)
        global_times = []

        for i, seed in enumerate(seeds):
            print(f"Simulation: #{i+1}")
            print(f"...simulating with random numbers (seed '{seed}')...")

            # Reinicia filas
            for q in queue_list:
                q.clients = 0
                q.losses = 0
                q.state_times = defaultdict(float)
                q.last_event_time = 0.0

            rng = RNG(seed=seed, limit=limit)
            gt = simulate(queue_list, queue_index, network, data, rng)
            global_times.append(gt)

            for idx, q in enumerate(queue_list):
                for state, t in q.state_times.items():
                    all_state_times[idx][state] += t
                all_losses[idx] += q.losses

        print(sep)
        print("=" * 16 + "    END OF SIMULATION   " + "=" * 17)
        print(sep)

        # Relatório agregado (média)
        n = len(seeds)
        print(sep)
        print("=" * 22 + "    REPORT   " + "=" * 22)
        print(sep)

        star = "*" * 57
        for idx, q in enumerate(queue_list):
            print(star)
            print(f"Queue:   {q.name} ({q.label()})")
            if q.min_arrival is not None:
                print(f"Arrival: {q.min_arrival} ... {q.max_arrival}")
            print(f"Service: {q.min_service} ... {q.max_service}")
            print(star)

            times = all_state_times[idx]
            total = sum(times.values())
            print(f"{'State':>9} {'Time':>20} {'Probability':>18}")
            for state in sorted(times.keys()):
                t = times[state] / n
                prob = (times[state] / total * 100) if total > 0 else 0
                print(f"   {state:>6}   {t:>20.4f}   {prob:>14.2f}%")
            print(f"Number of losses: {all_losses[idx]}")

        print(sep)
        print(f"Simulation average time: {sum(global_times)/n:.4f}")
        print(sep)

    else:
        # Simulação única (modo do enunciado do T1)
        print("Simulation: #1")
        if rnd_numbers:
            print(f"...simulating with provided list of {len(rnd_numbers)} random numbers...")
            rng = RNG(numbers=rnd_numbers, limit=len(rnd_numbers))
        else:
            print(f"...simulating with {limit} random numbers (no seed)...")
            rng = RNG(limit=limit)

        gt = simulate(queue_list, queue_index, network, data, rng)

        print(sep)
        print("=" * 16 + "    END OF SIMULATION   " + "=" * 17)
        print(sep)
        print_report(queue_list, gt, rng)


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != 'run':
        print("Uso: python simulator.py run <modelo.yml>")
        sys.exit(1)
    run(sys.argv[2])