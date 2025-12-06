async function addIncome() {
    const amount = document.getElementById("income-amount").value;

    const r = await fetch("/finance/add_income", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({amount})
    });

    const res = await r.json();
    document.getElementById("income-status").textContent = res.ok ? "Guardado" : "Error";
}


async function addSaving() {
    const amount = document.getElementById("saving-amount").value;

    const r = await fetch("/finance/add_saving", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({amount})
    });

    const res = await r.json();
    document.getElementById("saving-status").textContent = res.ok ? "Ahorro guardado" : "Error";
}


async function addCategory() {
    const name = document.getElementById("cat-name").value;
    const monthly = document.getElementById("cat-monthly").value;

    await fetch("/finance/add_category", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({name, monthly_goal:monthly})
    });

    loadCategories();
}

async function loadCategories() {
    const r = await fetch("/user/categories");
    const data = await r.json();
    const list = document.getElementById("cat-list");

    list.innerHTML = "";
    data.forEach(c => {
        list.innerHTML += `
            <div class="card">
                <b>${c.name}</b><br>
                Meta mensual: ${c.monthly_goal}
            </div>
        `;
    });
}
